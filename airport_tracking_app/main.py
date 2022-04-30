from datetime import date

from kivy import Logger
from kivy.app import App
from kivy.modules import inspector
from kivy.core.window import Window
from kivy.uix.button import Button
from sqlalchemy.exc import SQLAlchemyError
from database import Airport, City, Condition, Database
from travel_planner_app.main import TravelPlannerApp
from travel_planner_app.api_key import API_KEY
from travel_planner_app.rest import RESTConnection


class AirportButtons(Button):
    pass


class CityButtons(Button):
    pass


class AirportApp(App):
    def __init__(self, **kwargs):
        super(AirportApp, self).__init__(**kwargs)
        url = Database.construct_mysql_url('localhost', 33060, 'airports', 'root', 'cse1208')
        self.airport_database = Database(url)
        self.session = self.airport_database.create_session()
        self.airport_database.ensure_tables_exist()
        self.current_airport = None
        self.current_city = None
        self.api_key = API_KEY
        self.updated_forecast = None
        self.weather_connection = None
        self.connect_to_open_weather(port_api=443)

    def build(self):
        inspector.create_inspector(Window, self)

    def submit_data_airport(self, name, code, latitude, longitude):
        print(f'{len(name)}, {len(code)}, {len(latitude)}, {len(longitude)}')
        print(len(name) > 0 and len(code) > 0 and len(latitude) > 0 and len(longitude) > 0)
        if len(name) > 0 and len(code) > 0 and len(latitude) > 0 and len(longitude) > 0:
            try:
                self.commit_airport_to_database(code, latitude, longitude, name)
                self.set_current_airport(name)
                self.root.current = 'success_airport'
            except SQLAlchemyError:
                print('Database could not be updated.')
                self.root.ids.create_airport_error.text = 'Database could not be updated.' \
                                                          '\nThe information added may match an airport that' \
                                                          '\nis currently in the database'
            except ValueError:
                self.root.ids.create_airport_error.text = 'Invalid Input.\nPlease Try Again'
        else:
            self.root.ids.create_airport_error.text = 'Some information inputs were left blank, \nplease fill out all inputs'

    def commit_airport_to_database(self, code, latitude, longitude, name):
        airport = Airport(name=name, code=code, latitude=int(latitude), longitude=int(longitude))
        self.session.add(airport)
        self.session.commit()

    def submit_data_city(self, name, geographic_entity, latitude, longitude):
        if len(name) > 0 and len(geographic_entity) > 0 and len(latitude) > 0 and len(longitude) > 0:
            try:
                self.commit_city_to_database(geographic_entity, latitude, longitude, name)
                self.set_current_city(name)
                self.root.current = 'success_city'
            except SQLAlchemyError:
                print('Database could not be updated.')
                self.root.ids.create_city_error.text = 'Database could not be updated.' \
                                                       '\nThe information added may match a city that' \
                                                       '\nis currently in the database.'
            except ValueError:
                self.root.ids.create_city_error.text = 'Invalid Input\nPlease Try Again'
        else:
            self.root.ids.create_city_error.text = 'Some information inputs were left blank, \nplease fill out all inputs'

    def commit_city_to_database(self, geographic_entity, latitude, longitude, name):
        city = City(city_name=name, encompassing_geographic_entity=geographic_entity, latitude=int(latitude),
                    longitude=int(longitude))
        self.session.add(city)
        self.session.commit()

    def add_airports_spinner(self):
        values = [airport.name for airport in self.session.query(Airport).all()]
        self.root.ids.forecast_spinner.values = values

    def add_forecast(self, airport_name, date_1):
        try:
            airport = self.session.query(Airport).filter(Airport.name == airport_name).one()
            airport_id = airport.airport_id
            date_values = date_1.split('/')
            print('hi_1')
            try:
                forecasts = self.session.query(Condition).filter(Condition.date == date(int(date_values[2]), int(date_values[1]), int(date_values[0])) and Condition.airport_id == airport_id)
                self.root.ids.forecast.text = f'On {forecasts[0].date}, the weather will be:\n' \
                                              f'temperature: {forecasts[0].max_temperature}\n' \
                                              f'wind_speed: {forecasts[0].max_wind_speed}\n' \
                                              f'humidity: {forecasts[0].max_humidity}\n' \
                                              f'rain: {forecasts[0].rain}\n' \
                                              f'visibility: {forecasts[0].visibility}'
            except (IndexError, SQLAlchemyError, ValueError):
                for value in date_values:
                    try:
                        int(value)
                    except ValueError:
                        self.root.ids.check_forecast_error.text = 'The date input was incorrect,\n please type date in form DY/MN/YEAR.\n Ex: 1/7/2005'
                        return
                if int(date_values[0]) < 32 and int(date_values[1]) < 13 and 2000 < int(date_values[2]) < 3000:
                    print('hi')
                    self.request_onecall_for_place(airport.latitude, airport.longitude, date(int(date_values[2]), int(date_values[1]), int(date_values[0])), self.api_key)
                    self.root.current = 'check_forecast'
                    self.root.ids.check_forecast_error.text = 'Creating new forecasts for this airport. Please wait.'
                else:
                    self.root.ids.check_forecast_error.text = 'A value for day, month, or year is out of range or not accurate.'
        except SQLAlchemyError:
            self.root.current = 'check_forecast'
            self.root.ids.check_forecast_error.text = 'No airport was selected'

    def connect_to_open_weather(self, port_api=443):
        self.weather_connection = RESTConnection('api.openweathermap.org', port_api, '/data/2.5')

    def request_onecall_for_place(self, latitude, longitude, itinerary_date, api_key):
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
        self.create_new_forecasts()

    def on_records_not_loaded(self, _, error):
        Logger.error(f'{self.__class__.__name__}: {error}')

    def update_forecast(self, _, response):
        # print(dumps(response, indent=4, sort_keys=True))
        self.updated_forecast = response

    def create_new_forecasts(self):
        for day in self.updated_forecast['daily']:
            max_temperature = int(day['temp']['max'])
            min_temperature = int(day['temp']['min'])
            humidity = int(day['humidity'])
            wind_speed = int(day['wind_speed'])
            visibility = 10
            rain = int(day['pop'])
            forecast = Condition(date=date.fromtimestamp(int(day['dt'])), max_temperature=max_temperature,
                                 min_temperature=min_temperature, max_humidity=humidity, max_wind_speed=wind_speed,
                                 visibility=visibility, rain=rain)
            self.session.add(forecast)
            self.session.commit()

    def add_buttons(self):
        airports = self.session.query(Airport).all()
        cities = self.session.query(City).all()
        for airport in airports:
            self.root.ids.scroll_box_2.add_widget(AirportButtons(text=airport.name))
        for city in cities:
            self.root.ids.scroll_box_1.add_widget(CityButtons(text=city.city_name))

    def add_city(self, city):
        try:
            place = self.session.query(City).filter(City.city_name == city)[0]
            if self.current_airport.latitude - 1 <= place.latitude <= self.current_airport.latitude + 1 and \
                    self.current_airport.longitude - 1 <= place.longitude <= self.current_airport.longitude + 1:
                self.append_city_to_current_airport(place)
                self.root.ids.select_city_error.text = ''
            else:
                self.root.ids.select_city_error.text = 'The city you have chosen is not within range of this airport. Please select a in range city'
        except SQLAlchemyError:
            self.root.ids.select_city_error.text = 'The city you have selected could not be added to the database,' \
                                                   ' there may be multiple of this city or the database may have failed'

    def append_city_to_current_airport(self, place):
        self.current_airport.cities.append(place)
        self.session.add(self.current_airport)
        self.session.commit()

    def add_airport(self, airport):
        try:
            self.root.ids.select_airport_error.text = ''
            place = self.session.query(Airport).filter(Airport.name == airport)[0]
            if self.current_city.latitude - 1 <= place.latitude <= self.current_city.latitude + 1 and \
                    self.current_city.longitude - 1 <= place.longitude <= self.current_city.longitude + 1:
                self.append_airport_to_current_city(place)
            else:
                self.root.ids.select_airport_error.text = 'The airport you have chosen is not within range of this city. Please select a in range airport'
        except SQLAlchemyError:
            self.root.ids.select_airport_error.text = 'The airport you have selected could not be added to the database,' \
                                                      ' there may be multiple of this airport or the database may have failed'

    def append_airport_to_current_city(self, place):
        self.current_city.airports.append(place)
        self.session.add(self.current_city)
        self.session.commit()

    def set_current_city(self, city):
        self.current_city = self.session.query(City).filter(City.city_name == city).one()

    def set_current_airport(self, airport):
        self.current_airport = self.session.query(Airport).filter(Airport.name == airport).one()

    def delete_buttons(self):
        self.root.ids.scroll_box_1.clear_widgets()
        self.root.ids.scroll_box_2.clear_widgets()


def main():
    app = AirportApp()
    app.run()


if __name__ == '__main__':
    main()

# Things to clean up:
    # Re-organize main.py functions.
    # Add range determination to main.py.
    # Make screen take you back after making new city from button.
    # add view itinerary screen
    # make one call work
    # add method to update Condition if it doesn't exist for a day
