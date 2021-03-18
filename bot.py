import telebot
import os
import requests
import math
import psycopg2
from psycopg2 import sql
from telebot.types import Message, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton

from bot_settings import *


WELCOME_MESSAGE = """
Привет. Я бот для гео заметок. Я помогу тебе сохранить и запомнить самые выжные и интересные места.
Просмотреть список команд можно вызвав команду /help
"""
COMMANDS_DESCRIPTION = """
Список команд:

/start - Вывести приветственное сообщение
/help - Вывести список команд
/add - Добавить новое место
/list [size] - Просмотреть список сохраненных мест (по умолчанию 10 мест). Необязательный параметр size отвечает за размер списка
/reset_all - Удалить все сохраненные места
/settings - Изменить пользовательские настройки
/search - Поиск места по названию
/delete - Удаление места по названию

При отправке геопозиции будет выдан список мест в заданном радиусе (по умолчанию 500 метров)
"""

bot = telebot.TeleBot(TOKEN)


class DB:
    user = USER
    password = PASSWORD
    host = HOST
    port = PORT
    database = DATABASE

    @classmethod
    def connect(cls):
        con = psycopg2.connect(user=cls.user,
                               password=cls.password,
                               host=cls.host,
                               port=cls.port,
                               database=cls.database)
        return con

    @classmethod
    def insert(cls, cur, table_name, fields_list, values_list, conflict_field=None):
        query = sql.SQL("INSERT INTO {table}({fields}) VALUES({values})").format(
            table=sql.Identifier(table_name),
            fields=sql.SQL(', ').join(map(sql.Identifier, fields_list)),
            values=sql.SQL(', ').join(sql.Placeholder() * len(values_list)))
        if conflict_field:
            query = sql.Composed(
                [query, sql.SQL("ON CONFLICT ({field}) DO NOTHING").format(
                    field=sql.Identifier(conflict_field))])
        cur.execute(query, tuple(values_list))

    @classmethod
    def select(cls, cur, table_name, fields_list, cond_field_list=None, cond_value_list=None, order_field=None, limit=None):
        query = sql.SQL("SELECT {fields} FROM {table}").format(
            fields=sql.SQL(', ').join(map(sql.Identifier, fields_list)),
            table=sql.Identifier(table_name),
        )
        values = []
        if cond_field_list and cond_value_list:
            query = DB.__add_conditions(query, cond_field_list)
            values += cond_value_list
        if order_field:
            query = sql.Composed(
                [query, sql.SQL("ORDER BY {field}").format(
                    field=sql.Identifier(order_field))])
        if limit:
            query = sql.Composed(
                [query, sql.SQL("LIMIT {limit}").format(limit=sql.Placeholder())])
            values.append(limit)
        cur.execute(query, tuple(values))

    @classmethod
    def delete(cls, cur,  table_name, cond_field_list=None, cond_value_list=None):
        query = sql.SQL("DELETE FROM {table}").format(
            table=sql.Identifier(table_name)
        )
        values = []
        if cond_field_list and cond_value_list:
            query = DB.__add_conditions(query, cond_field_list)
            values += cond_value_list
        cur.execute(query, tuple(values))

    @classmethod
    def update(cls, cur, table_name, field_name, new_value, cond_field_list=None, cond_value_list=None):
        query = sql.SQL("UPDATE {table} SET {field} = {value}").format(
            table=sql.Identifier(table_name),
            field=sql.Identifier(field_name),
            value=sql.Placeholder()
        )
        values = [new_value]
        if cond_field_list and cond_value_list:
            query = DB.__add_conditions(query, cond_field_list)
            values += cond_value_list
        cur.execute(query, tuple(values))

    @classmethod
    def __add_conditions(cls, query, cond_field_list):
        conditions_list = [sql.SQL("{cond_field} = {cond_value}").format(
            cond_field=sql.Identifier(field),
            cond_value=sql.Placeholder()
        ) for field in cond_field_list]
        query = sql.Composed(
            [query, sql.SQL("WHERE {conditions}").format(
                conditions=sql.SQL(' AND ').join(conditions_list)
            )]
        )
        return query


class Place:
    def __init__(self, user_id, title):
        self.user_id = user_id
        self.title = title
        self.photo = None
        self.latitude = None
        self.longitude = None


def create_temporary_keyboard(*fields):
    table = ReplyKeyboardMarkup(one_time_keyboard=True, row_width=1)
    button_list = [KeyboardButton(field) for field in fields]
    table.add(*button_list)
    return table


@bot.message_handler(commands=['start'])
def send_welcome(message: Message):
    try:
        bot.send_message(message.from_user.id, WELCOME_MESSAGE)
    except Exception:
        bot.reply_to(message, 'Что-то пошло не так :(')


@bot.message_handler(commands=['help'])
def list_of_commands(message: Message):
    try:
        bot.send_message(message.from_user.id, COMMANDS_DESCRIPTION)
    except Exception:
        bot.reply_to(message, 'Что-то пошло не так :(')


@bot.message_handler(commands=['add'])
def add(message: Message):
    try:
        msg = bot.send_message(message.from_user.id, 'Введите название места')
        bot.register_next_step_handler(msg, add_name_step)
    except Exception:
        bot.reply_to(message, 'Что-то пошло не так :(')


def add_name_step(message: Message):
    try:
        if not message.text:
            raise ValueError()
        user_id = message.from_user.id
        title = message.text
        place = Place(user_id, title)
        msg = bot.send_message(user_id, 'Прикрепите фото')
        bot.register_next_step_handler(msg, add_photo_step, place=place)
    except ValueError:
        bot.reply_to(message, 'Недопустимое название')
    except Exception:
        bot.reply_to(message, 'Что-то пошло не так :(')


def add_photo_step(message: Message, place: Place):
    try:
        if message.photo:
            photo_info = bot.get_file(
                message.photo[len(message.photo)-1].file_id)
            place.photo = bot.download_file(photo_info.file_path)
        msg = bot.send_message(message.from_user.id, 'Отправьте геопозицию')
        bot.register_next_step_handler(
            msg, add_geoposition_step, place=place)
    except Exception:
        bot.reply_to(message, 'Что-то пошло не так :(')


def add_geoposition_step(message: Message, place: Place):
    try:
        if message.location:
            place.latitude = message.location.latitude
            place.longitude = message.location.longitude
        keyboard = create_temporary_keyboard('Да', 'Нет')
        msg = bot.send_message(message.from_user.id,
                               'Сохранить место?', reply_markup=keyboard)
        bot.register_next_step_handler(
            msg, add_save_in_database_step, place=place)
    except Exception:
        bot.reply_to(message, 'Что-то пошло не так :(')


def add_save_in_database_step(message: Message, place: Place):
    try:
        if message.text != 'Да':
            bot.send_message(message.from_user.id, 'Место не было сохранено',
                             reply_markup=ReplyKeyboardRemove())
            return

        con = DB.connect()
        cur = con.cursor()
        DB.insert(cur, table_name='users', fields_list=['user_id'], values_list=[
            place.user_id], conflict_field='user_id')

        fields_list = ['user_id', 'title',
                       'photo', 'latitude', 'longitude']
        values_list = [place.user_id, place.title,
                       place.photo, place.latitude, place.longitude]
        DB.insert(cur, table_name='places',
                  fields_list=fields_list, values_list=values_list)
        con.commit()
        bot.send_message(message.from_user.id, 'Место сохранено',
                         reply_markup=ReplyKeyboardRemove())
    except psycopg2.Error:
        if con:
            con.rollback()
        bot.reply_to(message, 'Ошибка при сохранении',
                     reply_markup=ReplyKeyboardRemove())
    except Exception:
        bot.reply_to(message, 'Что-то пошло не так :(',
                     reply_markup=ReplyKeyboardRemove())
    finally:
        if con:
            con.close()


@bot.message_handler(commands=['list'])
def list_command(message: Message):
    try:
        con = DB.connect()
        cur = con.cursor()

        list_size = DEFAULT_LIST_OF_PLACES_SIZE
        command = message.text.split(' ', maxsplit=1)
        if len(command) == 2:
            if int(command[1]) > 0:
                list_size = int(command[1])
            else:
                raise ValueError()
        else:
            DB.select(cur, table_name='users', fields_list=['list_size'], cond_field_list=[
                'user_id'], cond_value_list=[message.from_user.id])
            data = cur.fetchone()
            if data:
                list_size = data[0]
            else:
                bot.send_message(message.from_user.id,
                                 'У вас еще нет сохраненных мест')
                return

        fields_list = ['title', 'photo', 'latitude', 'longitude']
        DB.select(cur, table_name='places', fields_list=fields_list,
                  cond_field_list=['user_id'], cond_value_list=[message.from_user.id],
                  order_field='id', limit=list_size)
        place_list = cur.fetchall()
        if len(place_list) == 0:
            bot.send_message(message.from_user.id,
                             'У вас еще нет сохраненных мест')
            return
        for place in place_list:
            title, photo, latitude, longitude = place
            bot.send_message(message.from_user.id, title)
            if photo:
                bot.send_photo(message.from_user.id, photo=photo)
            if latitude and longitude:
                bot.send_location(
                    message.from_user.id, latitude=latitude, longitude=longitude)
    except ValueError:
        bot.reply_to(message, 'Длина списка должна быть целым числом больше 0')
    except psycopg2.Error:
        bot.reply_to(message, 'Ошибка при получении списка сохраненных мест')
    except Exception:
        bot.reply_to(message, 'Что-то пошло не так :(')
    finally:
        if con:
            con.close()


@bot.message_handler(commands=['reset_all'])
def reset_all(message: Message):
    try:
        keyboard = create_temporary_keyboard('Да', 'Нет')
        msg = bot.send_message(message.from_user.id,
                               'Удалить все сохраненные места?', reply_markup=keyboard)
        bot.register_next_step_handler(msg, reset_delete_from_database_step)
    except Exception:
        bot.reply_to(message, 'Что-то пошло не так :(')


def reset_delete_from_database_step(message: Message):
    try:
        if message.text != 'Да':
            bot.send_message(
                message.from_user.id, 'Удаление отменено', reply_markup=ReplyKeyboardRemove())
            return

        con = DB.connect()
        cur = con.cursor()
        DB.select(cur, table_name='places', fields_list=['title'], cond_field_list=[
                  'user_id'], cond_value_list=[message.from_user.id])
        cnt = cur.fetchone()
        if not cnt:
            bot.send_message(
                message.from_user.id, 'У вас еще нет сохраненных мест', reply_markup=ReplyKeyboardRemove())
            return
        DB.delete(cur, table_name='users', cond_field_list=[
                  'user_id'], cond_value_list=[message.from_user.id])
        con.commit()
        bot.send_message(
            message.from_user.id, 'Все сохраненные места удалены', reply_markup=ReplyKeyboardRemove())
    except psycopg2.Error:
        bot.reply_to(message, 'Ошибка при удалении',
                     reply_markup=ReplyKeyboardRemove())
        if con:
            con.rollback()
    except Exception:
        bot.reply_to(message, 'Что-то пошло не так :(',
                     reply_markup=ReplyKeyboardRemove())
    finally:
        if con:
            con.close()


@bot.message_handler(content_types=['location'])
def get_places_within_radius(message: Message):
    try:
        con = DB.connect()
        cur = con.cursor()
        radius = DEFAULT_RADIUS
        DB.select(cur, table_name='users', fields_list=[
                  'radius'], cond_field_list=['user_id'], cond_value_list=[message.from_user.id])
        data = cur.fetchone()
        if data:
            radius = data[0]
        else:
            bot.send_message(message.from_user.id,
                             'У вас еще нет сохраненных мест')
            return
        fields_list = ['title', 'photo', 'latitude', 'longitude']
        DB.select(cur, table_name='places', fields_list=fields_list,
                  cond_field_list=['user_id'], cond_value_list=[message.from_user.id])
        user_places_list = cur.fetchall()
        if len(user_places_list) == 0:
            bot.send_message(message.from_user.id,
                             'У вас еще нет сохраненных мест')
            return
        for place in user_places_list:
            title, photo, latitude, longitude = place
            if latitude and longitude:
                distance_meters = get_distance_meters(
                    latitude, longitude, message.location.latitude, message.location.longitude)
                if distance_meters <= radius:
                    bot.send_message(message.from_user.id, title)
                    if photo:
                        bot.send_photo(message.from_user.id, photo=photo)
                    bot.send_location(
                        message.from_user.id, latitude=latitude, longitude=longitude)
                    bot.send_message(message.from_user.id,
                                     f'Расстояние: {distance_meters:.2f} метров')
    except psycopg2.Error:
        bot.reply_to(message, 'Ошибка при получении списка сохраненных мест')
    except Exception:
        bot.reply_to(message, 'Что-то пошло не так :(')
    finally:
        if con:
            con.close()


def get_distance_meters(lat1d, lon1d, lat2d, lon2d):
    earth_radius_km = 6371.0

    lat1r = math.radians(lat1d)
    lon1r = math.radians(lon1d)
    lat2r = math.radians(lat2d)
    lon2r = math.radians(lon2d)

    u = math.sin((lat2r - lat1r) / 2)
    v = math.sin((lon2r - lon1r) / 2)
    return 2.0 * earth_radius_km * math.asin(math.sqrt(u ** 2 + math.cos(lat1r) * math.cos(lat2r) * v ** 2)) * 1000


@bot.message_handler(commands=['settings'])
def change_settings(message: Message):
    try:
        keyboard = create_temporary_keyboard(
            'Размер списка при вызове команды list', 'Радиус поиска ближайших мест')
        msg = bot.send_message(
            message.from_user.id, 'Выберите параметр для настройки', reply_markup=keyboard)
        bot.register_next_step_handler(msg, change_settings_new_value_input)
    except Exception:
        bot.reply_to(message, 'Что-то пошло не так :(')


def change_settings_new_value_input(message: Message):
    try:
        if message.text not in ['Размер списка при вызове команды list', 'Радиус поиска ближайших мест']:
            raise ValueError()
        msg = bot.send_message(
            message.from_user.id, 'Введите новое значение', reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(
            msg, change_settings_update, setting=message.text)
    except ValueError:
        bot.reply_to(message, 'Неверная настройка',
                     reply_markup=ReplyKeyboardRemove())
    except Exception:
        bot.reply_to(message, 'Что-то пошло не так :(',
                     reply_markup=ReplyKeyboardRemove())


def change_settings_update(message: Message, setting):
    try:
        con = DB.connect()
        cur = con.cursor()
        DB.insert(cur, table_name='users', fields_list=['user_id'], values_list=[
            message.from_user.id], conflict_field='user_id')
        value = message.text
        field_name = None
        if setting == 'Размер списка при вызове команды list':
            value = int(value)
            field_name = 'list_size'
        if setting == 'Радиус поиска ближайших мест':
            value = float(value)
            field_name = 'radius'
        if not value > 0:
            raise ValueError()
        DB.update(cur, table_name='users', field_name=field_name, new_value=value,
                  cond_field_list=['user_id'], cond_value_list=[message.from_user.id])
        con.commit()
        bot.send_message(message.from_user.id, 'Настройка изменена')
    except ValueError:
        bot.reply_to(message, 'Неверный тип параметра')
    except psycopg2.Error:
        bot.reply_to(message, 'Ошибка при изменении параметров')
        if con:
            con.rollback()
    except Exception:
        bot.reply_to(message, 'Что-то пошло не так :(')
    finally:
        if con:
            con.close()


@ bot.message_handler(commands=['search', 'delete'])
def search_or_delete(message: Message):
    try:
        con = DB.connect()
        cur = con.cursor()
        DB.select(cur, table_name='places', fields_list=['title'],
                  cond_field_list=['user_id'], cond_value_list=[message.from_user.id])
        title_list = [place[0] for place in cur.fetchall()]
        if len(title_list) == 0:
            bot.send_message(message.from_user.id,
                             'У вас еще нет сохраненных мест')
            return
        keyboard = create_temporary_keyboard(*title_list)
        msg = bot.send_message(message.from_user.id,
                               'Выберите место', reply_markup=keyboard)
        if message.text == '/search':
            bot.register_next_step_handler(msg, search_in_data_base)
        elif message.text == '/delete':
            bot.register_next_step_handler(
                msg, delete_from_data_base, title_list=title_list)
    except Exception:
        bot.reply_to(message, 'Что-то пошло не так :(',
                     reply_markup=ReplyKeyboardRemove())
    finally:
        if con:
            con.close()


def search_in_data_base(message: Message):
    try:
        title = message.text
        con = DB.connect()
        cur = con.cursor()
        DB.select(cur, table_name='places', fields_list=['photo', 'latitude', 'longitude'], cond_field_list=[
                  'user_id', 'title'], cond_value_list=[message.from_user.id, title])
        found_places = cur.fetchall()
        if len(found_places) == 0:
            bot.send_message(message.from_user.id, 'Место не найдено',
                             reply_markup=ReplyKeyboardRemove())
            return
        for photo, latitude, longitude in found_places:
            bot.send_message(message.from_user.id, title,
                             reply_markup=ReplyKeyboardRemove())
            if photo:
                bot.send_photo(message.from_user.id, photo=photo)
            if latitude and longitude:
                bot.send_location(message.from_user.id,
                                  latitude=latitude, longitude=longitude)
    except Exception:
        bot.reply_to(message, 'Что-то пошло не так :(',
                     reply_markup=ReplyKeyboardRemove())
    finally:
        if con:
            con.close()


def delete_from_data_base(message: Message, title_list):
    try:
        title = message.text
        if title not in title_list:
            bot.send_message(message.from_user.id, 'Место не найдено',
                             reply_markup=ReplyKeyboardRemove())
            return
        con = DB.connect()
        cur = con.cursor()
        DB.delete(cur, table_name='places', cond_field_list=[
                  'user_id', 'title'], cond_value_list=[message.from_user.id, title])
        con.commit()
        bot.send_message(message.from_user.id, 'Место удалено',
                         reply_markup=ReplyKeyboardRemove())
    except psycopg2.Error:
        bot.reply_to(message, 'Ошибка при удалении',
                     reply_markup=ReplyKeyboardRemove())
        if con:
            con.rollback()
    except Exception:
        bot.reply_to(message, 'Что-то пошло не так :(',
                     reply_markup=ReplyKeyboardRemove())
    finally:
        if con:
            con.close()


bot.enable_save_next_step_handlers(delay=1)
bot.load_next_step_handlers()

bot.polling(none_stop=True)
