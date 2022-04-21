from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Float, Date
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

Persisted = declarative_base()


class City(Persisted):
    __tablename__ = 'cities'
    city_id = Column(Integer, primary_key=True, autoincrement=True)
    city_name = Column(String(256), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    encompassing_geographic_entity = Column(String(256), nullable=False)
    venues = relationship('Venue', uselist=True, back_populates='city')
    airports = relationship('Airport', uselist=True, secondary='airport_cities', back_populates='cities')


class Venue(Persisted):
    __tablename__ = 'venues'
    venue_id = Column(Integer, primary_key=True, autoincrement=True)
    city_id = Column(Integer, ForeignKey('cities.city_id', ondelete='cascade'))
    venue_name = Column(String(256), nullable=False)
    venue_type = Column(String(256), nullable=False)
    condition = relationship('Condition', back_populates='venue', secondary='venue_conditions')
    city = relationship('City', back_populates='venues')


class Condition(Persisted):
    __tablename__ = 'conditions'
    condition_id = Column(Integer, primary_key=True, autoincrement=True)
    min_temperature = Column(Integer)
    max_temperature = Column(Integer)
    min_humidity = Column(Integer)
    max_humidity = Column(Integer)
    max_wind_speed = Column(Integer)
    open_weather_code = Column(Integer)
    date = Column(Date)
    venue = relationship('Venue', uselist=True, back_populates='condition', secondary='venue_conditions')
    airport = relationship('Airport', back_populates='conditions')


class VenueCondition(Persisted):
    __tablename__ = 'venue_conditions'
    venue_id = Column(Integer, ForeignKey('venues.venue_id', ondelete='CASCADE'), primary_key=True)
    condition_id = Column(Integer, ForeignKey('conditions.condition_id', ondelete='CASCADE'), primary_key=True)


class Airport(Persisted):
    __tablename__ = 'airports'
    airport_id = Column(Integer, primary_key=True)
    name = Column(String(256), nullable=False)
    code = Column(String(256))
    longitude = Column(Float)
    latitude = Column(Float)
    conditions = relationship('Condition', uselist=True, back_populates='airport')
    cities = relationship('City', uselist=True, secondary='airport_cities', back_populates='airports')


class AirportCity(Persisted):
    __tablename__ = 'airport_cities'
    airport_id = Column(Integer, ForeignKey('airports.airport_id', ondelete='CASCADE'), primary_key=True)
    city_id = Column(Integer, ForeignKey('cities.city_id', ondelete='CASCADE'), primary_key=True)


class Database(object):
    @staticmethod
    def construct_mysql_url(authority, port, database, username, password):
        return f'mysql+mysqlconnector://{username}:{password}@{authority}:{port}/{database}'

    @staticmethod
    def construct_in_memory_url():
        return 'sqlite:///'

    def __init__(self, url):
        self.engine = create_engine(url)
        self.Session = sessionmaker()
        self.Session.configure(bind=self.engine)

    def ensure_tables_exist(self):
        Persisted.metadata.create_all(self.engine)

    def create_session(self):
        return self.Session()
