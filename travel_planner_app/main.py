import math
from kivy.app import App
from kivy.modules import inspector
from kivy.core.window import Window
from datetime import timedelta, date
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from database import Database
from rest import RESTConnection
from api_key import API_KEY
from database import Airport, City, Venue, Condition, Itinerary, Review
from kivy.logger import Logger
from kivy.clock import Clock
import csv
from sqlalchemy.exc import SQLAlchemyError, ProgrammingError
from kivy.properties import StringProperty, NumericProperty

PRIME_MERIDIAN = [40, 0]
OPPOSITE_PRIME_MERIDIAN = [40, 180]


class ReviewScrollView(ScrollView):
    pass


class ItineraryView(BoxLayout):
    pass


class BlackLineX(BoxLayout):
    pass


class BlackLineY(BoxLayout):
    pass


def is_weather_ok_airport(airport, current_date):
    # Figure out severe weather
    next_day = current_date + timedelta(days=1)
    if len(airport.conditions) == 0:
        return True
    for forecast in airport.conditions:
        if next_day == forecast.date:
            if forecast.max_temperature < 45 and forecast.visibility > 5:
                return True
    return False


def find_distance(current_latitude, current_longitude, next_latitude, next_longitude):
    # need to figure out how to calculate whether you are still going East or West.
    distance = math.acos(math.sin(math.radians(current_latitude)) * math.sin(math.radians(next_latitude)) +
                         math.cos(math.radians(current_latitude)) * math.cos(math.radians(next_latitude)) *
                         math.cos(math.radians(next_longitude) - math.radians(current_longitude))) * 6371
    return distance


def is_weather_good_city(forecast):
    if 32 <= forecast.max_temperature <= 90 and 0 <= forecast.max_temperature <= 40 and forecast.max_wind_speed <= 20:
        return True
    return False


def does_weather_meet_venues_conditions(venue, forecast):
    if venue.condition:
        condition = venue.condition[0]
        if condition.min_temperature <= forecast.max_temperature <= condition.max_temperature and \
                condition.min_humidity <= forecast.max_humidity <= condition.max_humidity and \
                forecast.max_wind_speed <= condition.max_wind_speed:
            return True
        return False
    return True


def get_open_venues_list(city, forecast):
    venues_to_visit = []
    for venue in city.venues:
        if does_weather_meet_venues_conditions(venue, forecast):
            venues_to_visit.append(venue)
    return venues_to_visit


def search_for_indoor_events(event, venues_to_visit):
    for venue in venues_to_visit:
        if venue.venue_type == 'Indoor Theater' or venue.venue_type == 'Indoor Sports Arena':
            event = venue
    return event


def search_for_outdoor_sports(event, venues_to_visit):
    for venue in venues_to_visit:
        if venue.venue_type == 'Outdoor Sports Arena':
            event = venue
    return event


def search_for_outdoor_theater(event, venues_to_visit):
    for venue in venues_to_visit:
        if venue.venue_type == 'Outdoor Theater':
            event = venue
    return event


def get_positive_airports(current_airport, in_range_airports, destination):
    positive_range_airports = []
    for airport in in_range_airports:
        airport_x = find_distance(airport.latitude, airport.longitude, destination[0], destination[1])
        current_airport_x = find_distance(current_airport.latitude, current_airport.longitude, destination[0],
                                          destination[1])
        if airport_x < current_airport_x:
            positive_range_airports.append(airport)
    return positive_range_airports


class TravelPlannerApp(App):
    counter_text = NumericProperty(0)

    def __init__(self, **kwargs):
        super(TravelPlannerApp, self).__init__(**kwargs)
        self.url = None
        self.database = None
        self.session = None
        self.weather_connection = None
        self.geo_connection = None
        self.api_key = None
        self.validate_city_records = None
        self.current_location = None
        self.outdoor_sporting_events = 0
        self.outdoor_plays = 0
        self.outdoor_restaurants = 0
        self.current_date = date.today()
        self.updated_forecast = None
        self.previous_destination = None
        self.destination = None
        self.final_destination = None
        self.ratings_to_update = []
        self.queued_entertainment_itineraries = []
        self.queued_closest_itineraries = []
        self.airports = StringProperty('')
        self.cities = StringProperty('')
        self.welp = StringProperty('')
        self.amount_venues_welp = 0

    def build(self):
        inspector.create_inspector(Window, self)

    def connect_to_database(self, authority, port, database, username, password):
        try:
            url = construct_mysql_url(authority, port, database, username, password)
            database = Database(url)
            session = database.create_session()
            self.session = session
            self.database = database
            self.url = url
            self.root.current = 'loading_screen'
        except (SQLAlchemyError, ProgrammingError):
            self.root.current = 'home'
            self.root.ids.connection_error.text = 'The credentials given failed to connect to the remote database. Please re-enter your credentials'

    def connect_to_open_weather(self, api_key, port_api=443):
        try:
            self.weather_connection = RESTConnection('api.openweathermap.org', port_api, '/data/2.5')
            self.geo_connection = RESTConnection('api.openweathermap.org', port_api, '/geo/1.0')
            self.api_key = api_key
        except ConnectionError:
            self.root.current = 'home'
            self.root.ids.connection_error.text = 'OpenWeather will not connect, invalid API key.'

    def set_final_destination(self):
        airport = self.session.query(Airport).filter(Airport.name == 'Lincoln Airport').one()
        self.final_destination = airport
        self.destination = OPPOSITE_PRIME_MERIDIAN

    def get_places_to_validate(self):
        unvalidated_airports = []
        unvalidated_cities = []
        airports = self.session.query(Airport).all()
        cities = self.session.query(City).all()
        for airport in airports:
            if not airport.validated:
                unvalidated_airports.append(airports)
        for city in cities:
            if not city.validated:
                unvalidated_cities.append(cities)
        self.root.ids.amount_airports_unvalidated.text = str(len(unvalidated_airports))
        self.root.ids.amount_cities_unvalidated.text = str(len(unvalidated_cities))

    def add_locations_spinner(self):
        spinner_airports = [airport.name for airport in self.session.query(Airport).all(Airport.validated is False)]
        spinner_city = [city.city_name for city in self.session.query(City).all(City.validated is False)]
        self.root.ids.airports_spinner1.values = spinner_airports
        self.root.ids.city_spinner.values = spinner_city

    def get_venues_to_validate(self):
        venue_ids = set()
        unvalidated_reviews = self.session.query(Review).filter(Review.validated is False)
        for review in unvalidated_reviews:
            venue_ids.add(review.venue_id)
        unvalidated_venues = self.session.query(Venue.venue_id in venue_ids)
        return unvalidated_venues

    def validate_airport(self, airport_name):
        if airport_name == 'Select Airport to Validate':
            return
        airport = self.session.query(Airport).filter(Airport.name == airport_name).one()
        with open('airports.csv') as csvfile:
            reader = csv.DictReader(csvfile)
            for item in reader:
                if item['ICAO'] == airport.code:
                    if (float(item['Latitude']) - .009) <= airport.latitude <= (float(item['Latitude']) + .009) and \
                            (float(item['Longitude']) - .009) <= airport.longitude <= (float(item['Longitude']) + .009):
                        airport.validated = True
                        self.submit_data(airport)
                        self.root.ids.valid_airport_message.text = 'The airport location is validated.'
                        return True
            self.root.ids.invalid_airport_error.text = 'The airport location cannot be validated.'
            return False

    def validate_city(self, city_name):
        if city_name == 'Select City to Validate':
            return
        city = self.session.query(City).filter(City.city_name == city_name).one()
        self.geo_connection.send_request(
            'direct',
            {
                'q': city_name,
                'appid': API_KEY
            },
            None,
            self.on_records_loaded,
            self.on_records_not_loaded,
            self.on_records_not_loaded,
        )
        # Gave a forgiving range to allow for small error.
        if (self.validate_city_records['lat'] - .5) <= city.latitude <= (self.validate_city_records['lat'] + .5) \
                and (self.validate_city_records['lon'] - .5) <= city.longitude <= (
                self.validate_city_records['lon'] + .5) \
                and city.city_name == self.validate_city_records['name']:
            city.validated = True
            self.submit_data(city)
            self.root.ids.valid_city_message.text = 'The city location is validated.'
            return True
        else:
            self.root.ids.invalid_city_error.text = 'The city location cannot be validated.'
            return False

    def on_records_loaded(self, _, response):
        self.validate_city_records = response[0]

    def on_records_not_loaded(self, _, error):
        Logger.error(f'{self.__class__.__name__}: {error}')

    def populate_ratings_scroll_view(self):
        # Creates set of custom widgets and populates their child widgets with rating values.
        ratings = self.get_new_ratings()
        venues = []
        for rating in ratings:
            if rating.venue not in venues:
                venues.append(rating.venue)
        for venue in venues:
            view = ReviewScrollView()
            view.children[0].children[1].text = f'{venue.venue_name} = {venue.average_welp_score}'
            for rating in venue.reviews:
                view.children[0].children[0].children[0].add_widget(CheckBox())
                view.children[0].children[0].children[1].add_widget(
                    Label(text=f'score: {rating.score} id: {rating.review_id}'))
            self.root.ids.venue_and_review_scroll.add_widget(view)

    def check_state_of_checkboxes(self):
        # Checks to see if checkboxes and child widgets are pressed, updates based on accept or reject.
        accept = self.root.ids.accept_reject_review.text
        root = self.root.ids.venue_and_review_scroll
        venues = root.children
        for x in range(len(venues)):
            venue = root.children[x].children[0].children[1].text.split()
            venue = ' '.join(venue[:-2])
            checkboxes = root.children[x].children[0].children[0].children[0].children
            labels = root.children[x].children[0].children[0].children[1].children
            for i in range(len(checkboxes)):
                if checkboxes[i].active:
                    text = labels[i].text.split()
                    review_id = text[3]
                    self.update_rating(venue, review_id, accept)

    def get_average_rating(self, venue_name):
        try:
            return self.session.query(Venue).filter(Venue.name == venue_name).one().average_welp.score
        except SQLAlchemyError:
            return None

    def amount_of_needed_update_reviews(self):
        welp_venues = []
        welp = self.session.query(Venue).all()
        for venue in welp:
            if venue.welp_score_needs_update is True:
                welp_venues.append(welp)
        self.root.ids.welp_scores_updated.text = str(len(welp_venues))

    def get_new_ratings(self):
        new_ratings = self.session.query(Review).filter(Review.validated == False)
        return new_ratings

    def update_rating(self, venue_name, review_id, accept):
        try:
            venue = self.session.query(Venue).filter(Venue.venue_name == venue_name).one()
            review = self.session.query(Review).filter(Review.review_id == review_id).one()
            if accept == 'Accept':
                if venue.average_welp_score is None:
                    new_average_score = review.score
                else:
                    new_average_score = (len(venue.reviews) * venue.average_welp_score + review.score) / (
                            len(venue.reviews) + 1)
                venue.average_welp_score = new_average_score
                venue.welp_score_needs_update = False
                self.submit_data(venue)
                review.validated = True
                self.submit_data(review)
                self.root.ids.create_city_error.text = 'The selected reviews have successfully been updated.'
            else:
                self.delete_row(review)
                self.root.ids.create_city_error.text = 'The selected reviews have successfully been deleted from the database.'
        except SQLAlchemyError:
            self.root.ids.create_city_error.text = 'There seemed to be an issue when trying to submit your data to the database. ' \
                                                   'Try reloading the app and trying again.'

    def find_airport_to_cross_meridian(self, current_airport, in_range_airports):
        # Decided to use meridians on the longitude of the final destination to help travel around the world.
        # This method checks which hemosphere your in and then picks an airport on the opposite, while changing the destination.
        cross_airports = []
        if current_airport.longitude < 0:
            for airport in in_range_airports:
                if airport.longitude > 0:
                    cross_airports.append(airport)
        if current_airport.longitude > 0:
            for airport in in_range_airports:
                if airport.longitude < 0:
                    cross_airports.append(airport)
        max_distance = 0
        max_airport = None
        for airport in cross_airports:
            airport_distance = find_distance(current_airport.latitude, current_airport.longitude,
                                             airport.latitude, airport.longitude)
            if airport_distance > max_distance:
                max_airport = airport
        if max_airport is not None:
            if self.previous_destination != PRIME_MERIDIAN or self.previous_destination != OPPOSITE_PRIME_MERIDIAN:
                if self.destination == PRIME_MERIDIAN:
                    self.destination = OPPOSITE_PRIME_MERIDIAN
                elif self.destination == OPPOSITE_PRIME_MERIDIAN:
                    self.destination = PRIME_MERIDIAN
            else:
                self.destination = self.final_destination
        return max_airport

    def can_meridian_be_passed(self, current_airport, in_range_airports):
        airport = None
        if abs(find_distance(current_airport.latitude, current_airport.longitude, self.destination[0],
                             self.destination[1])) < 3500:
            airport = self.find_airport_to_cross_meridian(current_airport, in_range_airports)
        return airport

    def find_best_entertainment_airport_and_city(self, in_range_airports, current_date, current_airport, destination):
        best_airport = self.can_meridian_be_passed(current_airport, in_range_airports)
        positive_range_airports = get_positive_airports(current_airport, in_range_airports, destination)
        if not positive_range_airports:
            positive_range_airports = in_range_airports
        if best_airport is None:
            best_score = 0
            best_airport = positive_range_airports[0]
            best_city = positive_range_airports[0].cities[0]
            for airport in positive_range_airports:
                city = self.determine_best_city(airport, current_date)
                score = self.get_city_score(city, current_date)
                if score > best_score:
                    best_score = score
                    best_city = city
                    best_airport = airport
        else:
            best_city = self.determine_best_city(best_airport, current_date)
        return best_airport, best_city

    def find_closest_airport_to_destination(self, in_range_airports, destination, current_airport):
        best_option = self.can_meridian_be_passed(current_airport, in_range_airports)
        if best_option is None:
            min_distance = 1000000
            for airport in in_range_airports:
                if find_distance(airport.latitude, airport.longitude, destination[0],
                                 destination[1]) < min_distance:
                    min_distance = find_distance(airport.latitude, airport.longitude, destination[0],
                                                 destination[1])
                    best_option = airport
        return best_option

    def get_airports_in_range(self, current_airport, current_date):
        # Checks for range and weather.
        airports = self.session.query(Airport).all()
        in_range_airports = []
        for airport in airports:
            if find_distance(current_airport.latitude, current_airport.longitude, airport.latitude,
                             airport.longitude) <= 3500 and is_weather_ok_airport(airport, current_date):
                if len(airport.cities) != 0 and airport != current_airport:
                    in_range_airports.append(airport)
        if len(in_range_airports) == 0:
            for airport in airports:
                if find_distance(current_airport.latitude, current_airport.longitude,
                                 airport.latitude, airport.longitude) <= 3500 and airport != current_airport:
                    in_range_airports.append(airport)
        return in_range_airports

    def determine_best_city(self, airport, current_date):
        best_city = airport.cities[0]
        city_score = 0
        for city in airport.cities:
            if self.get_city_score(city, current_date) > city_score:
                city_score = self.get_city_score(city, current_date)
                best_city = city
        return best_city

    def get_city_score(self, city, current_date):
        # Algorithm decides an integer score of city in airport.cities.
        score = 0
        venues_open = 0
        forecasts_at_city = self.session.query(Condition).filter(Condition.city_id == city.city_id).count()
        if forecasts_at_city > 0:
            forecasts = self.session.query(Condition).filter(
                Condition.city_id == city.city_id)
            forecasts_on_date = []
            for forecast in forecasts:
                if forecast.date == current_date:
                    forecasts_on_date.append(forecast)
            if len(forecasts_on_date) > 1:
                forecast = self.session.query(Condition).filter(Condition.city_id == city.city_id)
                max_id = self.session.query(Condition).filter(Condition.city_id == city.city_id)[0].condition_id
                for condition in forecast:
                    if condition.condition_id > max_id:
                        condition_to_delete = self.session.query(Condition).filter(
                            Condition.condition_id == max_id).one()
                        max_id = condition.condition_id
                        self.delete_row(condition_to_delete)
                    elif condition.condition_id < max_id:
                        self.delete_row(condition)
                return self.get_city_score(city, current_date)
            if is_weather_good_city(forecasts[0]):
                score += 3
                score += len(get_open_venues_list(city, forecasts[0]))
            score += venues_open
            return score
        else:
            self.request_onecall_for_place(city.latitude, city.longitude, current_date, None, None, city, 'create',
                                           self.api_key)
            score = self.get_city_score(city, current_date)
            return score

    def determine_venues(self, venues_to_visit):
        # 'Indoor Restaurant', 'Outdoor Restaurant', 'Indoor Theater', 'Outdoor Theater', 'Indoor Sports Arena', 'Outdoor Sports Arena'
        venues = []
        event = None
        restaurant = None
        if self.outdoor_plays < self.outdoor_sporting_events:
            event = search_for_outdoor_theater(event, venues_to_visit)
            if event is None:
                event = search_for_outdoor_sports(event, venues_to_visit)
            if event is None:
                event = search_for_indoor_events(event, venues_to_visit)
        else:
            event = search_for_outdoor_sports(event, venues_to_visit)
            if event is None:
                event = search_for_outdoor_theater(event, venues_to_visit)
            if event is None:
                event = search_for_indoor_events(event, venues_to_visit)
        for venue in venues_to_visit:
            if venue.venue_type == 'Outdoor Restaurant':
                restaurant = venue
        if event is None:
            for venue in venues_to_visit:
                if venue.venue_type == 'Indoor Restaurant':
                    restaurant = venue
        if event is not None:
            venues.append(event)
        if restaurant is not None:
            venues.append(restaurant)
        return venues

    def add_subtract_day(self):
        # Advances current day by one.
        if self.counter_text < 7:
            self.current_date += timedelta(days=1)
            self.counter_text = self.counter_text + 1
            self.calender_day_changed()

    def create_closest_itinerary_day(self, destination, current_date, current_airport):
        airport = self.find_closest_airport_to_destination(self.get_airports_in_range(current_airport, current_date),
                                                           destination, current_airport)
        city = self.determine_best_city(airport, current_date)
        city_forecast_length = self.session.query(Condition).filter(Condition.city_id == city.city_id).count()
        if city_forecast_length == 0:
            self.request_onecall_for_place(airport.latitude, airport.longitude, current_date, None, None, city,
                                           'create', self.api_key)
            self.create_closest_itinerary_day(destination, current_date, current_airport)
        elif city_forecast_length > 0:
            city_forecasts = self.session.query(Condition).filter(Condition.city_id == city.city_id)
            city_forecast = []
            for forecast in city_forecasts:
                if forecast.date == current_date:
                    city_forecast.append(forecast)
            if len(city_forecast) == 1:
                forecast = city_forecast[0]
                venues_to_visit = get_open_venues_list(city, forecast)
                venues = self.determine_venues(venues_to_visit)
                leave_from_airport = None
                if len(city.airports) > 1:
                    for airport_2 in city.airports:
                        if airport_2 != airport:
                            leave_from_airport = airport_2
                if leave_from_airport is not None:
                    itinerary = Itinerary(airport=airport.name, city=city.city_name, venues=venues, date=current_date,
                                          itinerary_type='Close', airport_left_from=leave_from_airport.name)
                else:
                    itinerary = Itinerary(airport=airport.name, city=city.city_name, venues=venues, date=current_date,
                                          itinerary_type='Close', airport_left_from=airport.name)
                self.queued_closest_itineraries.append(itinerary)
            return airport

    def create_entertainment_itinerary(self, destination, current_date, current_airport):
        airport, city = self.find_best_entertainment_airport_and_city(
            self.get_airports_in_range(current_airport, current_date), current_date, current_airport, destination)
        city_forecasts = self.session.query(Condition).filter(Condition.city_id == city.city_id)
        city_forecast = []
        for forecast in city_forecasts:
            if forecast.date == current_date:
                city_forecast.append(forecast)
        if len(city_forecast) > 1:
            while len(city_forecast) > 1:
                self.delete_row(city_forecast[0])
                city_forecast.pop(0)
        venues_to_visit = get_open_venues_list(city, city_forecast[0])
        venues = self.determine_venues(venues_to_visit)
        leave_from_airport = None
        if len(city.airports) > 1:
            for airport_2 in city.airports:
                if airport_2 != airport:
                    leave_from_airport = airport_2
        if leave_from_airport is not None:
            itinerary = Itinerary(airport=airport.name, city=city.city_name, venues=venues, date=current_date,
                                  itinerary_type='Entertain', airport_left_from=leave_from_airport.name)
        else:
            itinerary = Itinerary(airport=airport.name, city=city.city_name, venues=venues, date=current_date,
                                  itinerary_type='Entertain', airport_left_from=airport.name)
        self.queued_entertainment_itineraries.append(itinerary)
        return airport

    def get_previous_itinerary(self):
        itineraries = self.session.query(Itinerary).filter(Itinerary.date < self.current_date)
        return itineraries

    def get_current_location(self):
        itinerary = self.session.query(Itinerary).filter(Itinerary.date == self.current_date).one()
        airport = self.session.query(Airport).filter(Airport.name == itinerary.airport).one()
        return airport.latitude, airport.longitude

    def prepare_itineraries(self):
        # takes all itineraries and finds which ones are ahead of the current day.
        itineraries = self.session.query(Itinerary).all()
        current_itineraries = []
        for itinerary in itineraries:
            if itinerary.date >= self.current_date:
                current_itineraries.append(itinerary)
        # updates itineraries and then gets amount of new itineraries to be made.
        max_date = self.current_date
        current_airport = None
        if len(current_itineraries) > 0:
            for itinerary in current_itineraries:
                self.update_existing_itinerary(itinerary)
                if itinerary.date > max_date:
                    max_date = itinerary.date
                    current_airport = self.session.query(Airport).filter(Airport.name == itinerary.airport).one()
        else:
            max_date = self.current_date
            current_airport = self.final_destination
        new_itineraries = (7 - (max_date - self.current_date).days)
        # creates new itineraries.
        closest_airport = current_airport
        entertainment_airport = current_airport
        for i in range(new_itineraries):
            max_date += timedelta(days=1)
            closest_airport = self.create_closest_itinerary_day(self.destination, max_date, closest_airport)
            entertainment_airport = self.create_entertainment_itinerary(self.destination, max_date,
                                                                        entertainment_airport)
            for itinerary in self.queued_closest_itineraries:
                if itinerary.date == max_date:
                    airport = self.session.query(Airport).filter(Airport.name == itinerary.airport).one()
                    closest_airport = airport
            for itinerary in self.queued_entertainment_itineraries:
                if itinerary.date == max_date:
                    airport = self.session.query(Airport).filter(Airport.name == itinerary.airport).one()
                    entertainment_airport = airport
        self.set_next_itineraries(self.queued_closest_itineraries)
        self.set_next_itineraries(self.queued_entertainment_itineraries)

    def set_next_itineraries(self, itineraries):
        try:
            for i in range(len(itineraries)):
                itineraries[i].next_itinerary = itineraries[i + 1].city
        except IndexError:
            last_itinerary = None
            last_date = itineraries[0].date + timedelta(days=-1)
            for itinerary in self.session.query(Itinerary).all():
                if itinerary.date == last_date:
                    last_itinerary = itinerary
            if last_itinerary is not None:
                last_itinerary.next_itinerary = itineraries[0].city

    def update_existing_itinerary(self, itinerary):
        airport = self.session.query(Airport).filter(Airport.name == itinerary.airport).one()
        future_forecasts = []
        for condition in airport.conditions:
            if condition.date >= self.current_date:
                future_forecasts.append(condition)
        if len(future_forecasts) > 0:
            outdated_forecasts = self.session.query(Condition).filter(Condition.airport_id == airport.airport_id)
            outdated_forecast = outdated_forecasts[0]
            for forecast in outdated_forecasts:
                if forecast.date == itinerary.date:
                    outdated_forecast = forecast
            self.request_onecall_for_place(airport.latitude, airport.longitude, itinerary.date, outdated_forecast,
                                           airport, None, 'update', self.api_key)
        else:
            self.request_onecall_for_place(airport.latitude, airport.longitude, itinerary.date,
                                           None, airport, None, 'create', self.api_key)

    def populate_itinerary_view(self):
        self.root.ids.itinerary_scroll.size_hint_min_x = 300 * (
                (len(self.queued_closest_itineraries) + len(self.queued_entertainment_itineraries)) / 2)
        root_1 = self.root.ids.entertainment_itinerary
        root_2 = self.root.ids.closest_itinerary
        for itinerary in self.queued_closest_itineraries:
            itinerary_view = ItineraryView()
            if len(itinerary.venues) == 2:
                itinerary_view.children[1].children[0].text = f'Entertainment: {itinerary.venues[0].venue_name}'
                itinerary_view.children[1].children[1].text = f'Eat at: {itinerary.venues[1].venue_name}'
            elif len(itinerary.venues) == 1:
                itinerary_view.children[1].children[0].text = 'Entertainment: None'
                itinerary_view.children[1].children[1].text = f'Eat at: {itinerary.venues[0].venue_name}'
            itinerary_view.children[1].children[2].text = f'Go to: {itinerary.city}'
            itinerary_view.children[1].children[3].text = f'Arrive At: {itinerary.airport}'
            itinerary_view.children[1].children[4].text = f'Airport Leave: {itinerary.airport_left_from}'
            itinerary_view.children[1].children[5].text = f'Date {itinerary.date}'
            root_1.add_widget(itinerary_view)
        for itinerary in self.queued_entertainment_itineraries:
            itinerary_view = ItineraryView()
            if len(itinerary.venues) == 2:
                itinerary_view.children[1].children[0].text = f'Entertainment: {itinerary.venues[0].venue_name}'
                itinerary_view.children[1].children[1].text = f'Eat at: {itinerary.venues[1].venue_name}'
            elif len(itinerary.venues) == 1:
                itinerary_view.children[1].children[0].text = 'Entertainment: None'
                itinerary_view.children[1].children[1].text = f'Eat at: {itinerary.venues[0].venue_name}'
            itinerary_view.children[1].children[2].text = f'Go to: {itinerary.city}'
            itinerary_view.children[1].children[3].text = f'Arrive At: {itinerary.airport}'
            itinerary_view.children[1].children[4].text = f'Airport Leave: {itinerary.airport_left_from}'
            itinerary_view.children[1].children[5].text = f'Date {itinerary.date}'
            root_2.add_widget(itinerary_view)

    def request_onecall_for_place(self, latitude, longitude, itinerary_date, outdated_forecast, airport, city,
                                  update_or_create, api_key):
        self.weather_connection.send_request(
            'onecall',
            {
                'lat': latitude,
                'lon': longitude,
                'appid': api_key
            },
            None,
            self.update_forecast,
            self.on_records_not_loaded,
            self.on_records_not_loaded,
        )
        if update_or_create == 'update':
            self.update_old_forecast(itinerary_date, outdated_forecast)
        elif update_or_create == 'create':
            self.create_new_forecasts(airport, city)
        else:
            pass

    def update_old_forecast(self, itinerary_date, outdated_forecast):
        forecast = None
        for day in self.updated_forecast['daily']:
            if date.fromtimestamp(int(day['dt'])) == itinerary_date:
                forecast = day
        if forecast is not None:
            outdated_forecast.max_temperature = int(forecast['temp']['max'])
            outdated_forecast.min_temperature = int(forecast['temp']['min'])
            outdated_forecast.humidity = int(forecast['humidity'])
            outdated_forecast.rain = int(forecast['pop'])
            outdated_forecast.visibility = 10
            outdated_forecast.max_wind_speed = int(forecast['wind_speed'])
            new_forecast = outdated_forecast
            self.submit_data(new_forecast)
        else:
            pass

    def update_forecast(self, _, response):
        self.updated_forecast = response

    def create_new_forecasts(self, airport, city):
        for day in self.updated_forecast['daily']:
            max_temperature = int(day['temp']['max'])
            min_temperature = int(day['temp']['min'])
            humidity = int(day['humidity'])
            wind_speed = int(day['wind_speed'])
            visibility = 10
            rain = int(day['pop'])
            if city is None:
                forecast = Condition(date=date.fromtimestamp(int(day['dt'])), max_temperature=max_temperature,
                                     min_temperature=min_temperature, max_humidity=humidity, max_wind_speed=wind_speed,
                                     visibility=visibility, rain=rain, airport=airport)
            else:
                forecast = Condition(date=date.fromtimestamp(int(day['dt'])), max_temperature=max_temperature,
                                     min_temperature=min_temperature, max_humidity=humidity, max_wind_speed=wind_speed,
                                     visibility=visibility, rain=rain, city=city)
            self.submit_data(forecast)

    def empty_credentials_screen(self):
        if self.root.ids.database_authority.text or self.root.ids.database_portnumber.text or self.root.ids.database_name.text or self.root.ids.database_username.text or self.root.ids.database_password.text or self.root.ids.api_authority.text or self.root.ids.api_portnumber.text or self.root.ids.api_key.text != '':
            self.root.ids.empty_fields_error.text = 'Text boxes were left blank, please fill in proper information.'

    def submit_data(self, data):
        try:
            if type(data) is list:
                for item in data:
                    self.session.add(item)
            else:
                self.session.add(data)
            self.session.commit()
        except SQLAlchemyError:
            pass

    def delete_row(self, item):
        try:
            item[0] = item[0]
            for data in item:
                self.session.delete(data)
        except (IndexError, ValueError, TypeError):
            self.session.delete(item)
        self.session.commit()

    def calender_day_changed(self):
        next_itineraries = []
        for itinerary in self.session.query(Itinerary).all():
            if itinerary.date == self.current_date:
                next_itineraries.append(itinerary)
        if next_itineraries:
            lift_off = True
            for itinerary in next_itineraries:
                airport_arrive = self.session.query(Airport).filter(Airport.name == itinerary.airport).one()
                airport_leave = self.session.query(Airport).filter(Airport.name == itinerary.airport_left_from).one()
                if airport_leave == airport_arrive:
                    lift_off = self.check_lift_off_acceptable(airport_arrive, itinerary.date)
                else:
                    lift_off_1 = self.check_lift_off_acceptable(airport_arrive, itinerary.date)
                    lift_off_2 = self.check_lift_off_acceptable(airport_leave, itinerary.date)
                    lift_off = True
                    if not lift_off_2 or not lift_off_1:
                        lift_off = False
            if not lift_off:
                # advance all proposed by One:
                itineraries = self.session.query(Itinerary).all()
                for itinerary in itineraries:
                    if itinerary.itinerary_type == 'Entertain' or itinerary.itinerary_type == 'Close':
                        itinerary.date = itinerary.date + timedelta(days=1)
            if lift_off:
                current_itineraries = []
                itineraries = self.session.query(Itinerary).all()
                for itinerary in itineraries:
                    if itinerary.date == self.current_date:
                        current_itineraries.append(itinerary)
                for itinerary in current_itineraries:
                    if itinerary.selected:
                        itinerary.itinerary_type = 'Past'
                    if not itinerary.selected:
                        self.delete_row(itinerary)

    def check_lift_off_acceptable(self, airport, current_date):
        self.request_onecall_for_place(airport.latitude, airport.longitude, None, None, None, None, 'Lift Off',
                                       self.api_key)
        forecast = self.updated_forecast
        lift_off = True
        for hour in forecast['hourly']:
            if date.fromtimestamp(int(hour['dt'])) == current_date:
                if hour['visibility'] < 5000:
                    lift_off = False
        if 'alerts' in forecast:
            lift_off = False
        return lift_off

    def add_airports_spinner(self):
        values = [airport.name for airport in self.session.query(Airport).all()]
        self.root.ids.airport_spinner.values = values

    def add_airports_city_spinner(self):
        values = [airport.name for airport in self.session.query(Airport).all()] and [city.city_name for city in
                                                                                      self.session.query(City).all()]
        self.root.ids.airports_city_spinner1.values = values

    def delete_buttons(self):
        self.root.ids.scroll_box_1.clear_widgets()
        self.root.ids.scroll_box_2.clear_widgets()

    def loading_screen(self, **kwargs):
        super(TravelPlannerApp, self).__init__(**kwargs)
        Clock.schedule_once(self.load, 3)

    def load(self, app):
        self.root.current = 'mainmenu1'


def construct_mysql_url(authority, port, database, username, password):
    return f'mysql+mysqlconnector://{username}:{password}@{authority}:{port}/{database}'


def construct_in_memory_url():
    return 'sqlite:///'


def main():
    app = TravelPlannerApp()
    app.run()


if __name__ == '__main__':
    main()
