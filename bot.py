import telebot
import math
import psycopg2
from psycopg2 import sql
from telebot.types import Message, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton

from bot_settings import *

import os
from flask import Flask, request

WELCOME_MESSAGE = """
Привет. Я бот гео заметок. Я помогу тебе сохранить и запомнить самые важные и интересные места.
Просмотреть список команд можно вызвав команду /help
"""

ERROR_MESSAGE = "Что-то пошло не так :("

COMMANDS_DESCRIPTION = """
Список команд:

/start - Вывести приветственное сообщение
/help - Вывести список доступных команд
/add - Добавить новое место
/list [size] - Просмотреть список из последних сохраненных мест (по умолчанию 10 мест). Необязательный параметр size отвечает за размер списка
/reset_all - Удалить все данные пользователя
/settings - Изменить пользовательские настройки
/search - Поиск места по названию
/delete - Удаление места по названию
/add_friend - Добавить контакт друга
/delete_friend - Удалить друга

При отправке координат будет выдан список мест в заданном радиусе (по умолчанию 500 метров)
"""

bot = telebot.TeleBot(TOKEN)
server = Flask(__name__)


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
    def insert(cls, cur, table_name, fields_list, values_list, conflict_field_list=None):
        query = sql.SQL("INSERT INTO {table}({fields}) VALUES({values}) ").format(
            table=sql.Identifier(table_name),
            fields=sql.SQL(', ').join(map(sql.Identifier, fields_list)),
            values=sql.SQL(', ').join(sql.Placeholder() * len(values_list)))
        if conflict_field_list:
            query = sql.Composed(
                [query, sql.SQL("ON CONFLICT ({fields}) DO NOTHING ").format(
                    fields=sql.SQL(', ').join(map(sql.Identifier, conflict_field_list)))])
        cur.execute(query, tuple(values_list))

    @classmethod
    def select(cls, cur, table_name, fields_list, cond_field_list=None, cond_value_list=None, order_field=None, reverse_order=False, limit=None):
        query = sql.SQL("SELECT {fields} FROM {table} ").format(
            fields=sql.SQL(', ').join(map(sql.Identifier, fields_list)),
            table=sql.Identifier(table_name)
        )
        values = []
        if cond_field_list and cond_value_list:
            query = DB.__add_conditions(query, cond_field_list)
            values += cond_value_list
        if order_field:
            query = sql.Composed(
                [query, sql.SQL("ORDER BY {field} ").format(
                    field=sql.Identifier(order_field))])
            if reverse_order:
                query = sql.Composed([query, sql.SQL("DESC ")])
        if limit:
            query = sql.Composed(
                [query, sql.SQL("LIMIT {limit} ").format(limit=sql.Placeholder())])
            values.append(limit)
        cur.execute(query, tuple(values))

    @classmethod
    def delete(cls, cur, table_name, cond_field_list=None, cond_value_list=None):
        query = sql.SQL("DELETE FROM {table} ").format(
            table=sql.Identifier(table_name)
        )
        values = []
        if cond_field_list and cond_value_list:
            query = DB.__add_conditions(query, cond_field_list)
            values += cond_value_list
        cur.execute(query, tuple(values))

    @classmethod
    def update(cls, cur, table_name, field_name, new_value, cond_field_list=None, cond_value_list=None):
        query = sql.SQL("UPDATE {table} SET {field} = {value} ").format(
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
            [query, sql.SQL("WHERE {conditions} ").format(
                conditions=sql.SQL(' AND ').join(conditions_list)
            )]
        )
        return query


class Place:
    def __init__(self, user_id, user_name, title):
        self.user_id = user_id
        self.user_name = user_name
        self.title = title
        self.photo = None
        self.latitude = None
        self.longitude = None


def create_temporary_reply_keyboard(*fields):
    table = ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    button_list = [KeyboardButton(field) for field in fields]
    table.add(*button_list)
    return table


@bot.message_handler(commands=['start'])
def send_welcome_message(message: Message):
    try:
        bot.send_message(message.from_user.id, WELCOME_MESSAGE)
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE)


@bot.message_handler(commands=['help'])
def list_of_commands(message: Message):
    try:
        bot.send_message(message.from_user.id, COMMANDS_DESCRIPTION)
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE)


@bot.message_handler(commands=['add'])
def add(message: Message):
    try:
        msg = bot.send_message(message.from_user.id, 'Введите название места')
        bot.register_next_step_handler(msg, add_name_step)
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE)


def add_name_step(message: Message):
    try:
        if not message.text:
            raise ValueError()
        user_id = message.from_user.id
        user_name = message.from_user.first_name
        title = message.text
        place = Place(user_id, user_name, title)
        keyboard = create_temporary_reply_keyboard('Пропустить')
        msg = bot.send_message(
            user_id, 'Прикрепите фото', reply_markup=keyboard)
        bot.register_next_step_handler(msg, add_photo_step, place=place)
    except ValueError:
        bot.reply_to(message, 'Недопустимое значение',
                     reply_markup=ReplyKeyboardRemove())
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE,
                     reply_markup=ReplyKeyboardRemove())


def add_photo_step(message: Message, place: Place):
    try:
        if message.photo:
            photo_info = bot.get_file(
                message.photo[len(message.photo)-1].file_id)
            place.photo = bot.download_file(photo_info.file_path)
        keyboard = create_temporary_reply_keyboard('Пропустить')
        msg = bot.send_message(
            message.from_user.id, 'Отправьте геопозицию', reply_markup=keyboard)
        bot.register_next_step_handler(
            msg, add_geoposition_step, place=place)
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE,
                     reply_markup=ReplyKeyboardRemove())


def add_geoposition_step(message: Message, place: Place):
    try:
        if message.location:
            place.latitude = message.location.latitude
            place.longitude = message.location.longitude
        keyboard = create_temporary_reply_keyboard('Да', 'Нет')
        msg = bot.send_message(message.from_user.id,
                               'Сохранить место?', reply_markup=keyboard)
        bot.register_next_step_handler(
            msg, add_save_in_database_step, place=place)
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE,
                     reply_markup=ReplyKeyboardRemove())


def add_save_in_database_step(message: Message, place: Place):
    con = None
    cur = None

    try:
        if message.text != 'Да':
            bot.send_message(message.from_user.id, 'Место не было сохранено',
                             reply_markup=ReplyKeyboardRemove())
            return

        con = DB.connect()
        cur = con.cursor()
        DB.insert(cur, table_name='users', fields_list=['user_id', 'user_name'], values_list=[
                  place.user_id, place.user_name], conflict_field_list=['user_id'])
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
        bot.reply_to(message, 'Ошибка при сохранении ',
                     reply_markup=ReplyKeyboardRemove())
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE,
                     reply_markup=ReplyKeyboardRemove())
    finally:
        if con:
            con.close()


@bot.message_handler(commands=['list'])
def list_command(message: Message):
    con = None
    cur = None

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
                  order_field='id', reverse_order=True, limit=list_size)
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
        bot.reply_to(message, ERROR_MESSAGE)
    finally:
        if con:
            con.close()


@bot.message_handler(commands=['reset_all'])
def reset_all(message: Message):
    try:
        keyboard = create_temporary_reply_keyboard('Отмена')
        msg = bot.send_message(message.from_user.id,
                               'Для удаления всех данных пользователя введите слово "Удалить".', reply_markup=keyboard)
        bot.register_next_step_handler(msg, reset_delete_from_database_step)
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE,
                     reply_markup=ReplyKeyboardRemove())


def reset_delete_from_database_step(message: Message):
    con = None
    cur = None

    try:
        if message.text != 'Удалить':
            bot.send_message(
                message.from_user.id, 'Удаление отменено', reply_markup=ReplyKeyboardRemove())
            return
        
        con = DB.connect()
        cur = con.cursor()
        DB.delete(cur, table_name='users', cond_field_list=[
                  'user_id'], cond_value_list=[message.from_user.id])
        con.commit()
        bot.send_message(
            message.from_user.id, 'Все данные удалены', reply_markup=ReplyKeyboardRemove())
    except psycopg2.Error:
        bot.reply_to(message, 'Ошибка при удалении',
                     reply_markup=ReplyKeyboardRemove())
        if con:
            con.rollback()
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE,
                     reply_markup=ReplyKeyboardRemove())
    finally:
        if con:
            con.close()


@bot.message_handler(content_types=['location'])
def get_places_within_radius(message: Message):
    con = None
    cur = None

    try:
        con = DB.connect()
        cur = con.cursor()
        radius = DEFAULT_RADIUS
        DB.select(cur, table_name='users', fields_list=[
                  'radius', 'friend_place_visible'], cond_field_list=['user_id'], cond_value_list=[message.from_user.id])
        data = cur.fetchone()
        if data:
            radius = data[0]
        else:
            bot.send_message(message.from_user.id,
                             'У вас еще нет сохраненных мест')
            return
        visible = data[1]
        fields_list = ['title', 'photo', 'latitude', 'longitude']
        if visible:
            cur.execute("SELECT title, photo, latitude, longitude FROM places WHERE user_id IN (SELECT user_id FROM friends WHERE friend_id = %s) OR user_id = %s",
                        (message.from_user.id, message.from_user.id))
        else:
            DB.select(cur, table_name='places', fields_list=fields_list,
                      cond_field_list=['user_id'], cond_value_list=[message.from_user.id])
        user_places_list = cur.fetchall()
        if len(user_places_list) == 0:
            bot.send_message(message.from_user.id,
                             'Сохраненные места не найдены')
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
        bot.reply_to(message, ERROR_MESSAGE)
    finally:
        if con:
            con.close()


def get_distance_meters(lat1d, long1d, lat2d, long2d):
    earth_radius_m = 6371009

    lat1 = math.radians(lat1d)
    long1 = math.radians(long1d)
    lat2 = math.radians(lat2d)
    long2 = math.radians(long2d)

    cl1 = math.cos(lat1)
    cl2 = math.cos(lat2)
    sl1 = math.sin(lat1)
    sl2 = math.sin(lat2)
    delta = long2 - long1
    cdelta = math.cos(delta)
    sdelta = math.sin(delta)

    y = math.sqrt((cl2 * sdelta) ** 2 + (cl1 * sl2 - sl1 * cl2 * cdelta) ** 2)
    x = sl1 * sl2 + cl1 * cl2 * cdelta

    ad = math.atan2(y, x)
    return ad * earth_radius_m


@bot.message_handler(commands=['settings'])
def change_settings(message: Message):
    try:
        settings = [
            'Размер списка (list)', 'Радиус поиска ближайших мест', 'Просмотр мест друзей']
        keyboard = create_temporary_reply_keyboard(*settings)
        msg = bot.send_message(
            message.from_user.id, 'Выберите параметр для настройки', reply_markup=keyboard)
        bot.register_next_step_handler(
            msg, change_settings_new_value_input, settings=settings)
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE,
                     reply_markup=ReplyKeyboardRemove())


def change_settings_new_value_input(message: Message, settings):
    try:
        if message.text not in settings:
            raise ValueError()
        reply_markup = ReplyKeyboardRemove()
        if message.text == 'Просмотр мест друзей':
            reply_markup = create_temporary_reply_keyboard(
                'Включить', 'Выключить')
        msg = bot.send_message(
            message.from_user.id, 'Введите новое значение', reply_markup=reply_markup)
        bot.register_next_step_handler(
            msg, change_settings_update, setting=message.text)
    except ValueError:
        bot.reply_to(message, 'Неверная настройка',
                     reply_markup=ReplyKeyboardRemove())
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE,
                     reply_markup=ReplyKeyboardRemove())


def change_settings_update(message: Message, setting):
    con = None
    cur = None

    try:
        con = DB.connect()
        cur = con.cursor()
        DB.insert(cur, table_name='users', fields_list=['user_id', 'user_name'], values_list=[
                  message.from_user.id, message.from_user.first_name], conflict_field_list=['user_id'])
        value = message.text
        field_name = None
        if setting == 'Размер списка (list)':
            value = int(value)
            field_name = 'list_size'
            if not value > 0:
                raise RuntimeError(
                    'Размер списка должен быть целым числом больше 0')
        elif setting == 'Радиус поиска ближайших мест':
            value = float(value)
            field_name = 'radius'
            if not value > 0:
                raise RuntimeError('Радиус поиска должен быть больше 0')
        elif setting == 'Просмотр мест друзей':
            if value == 'Включить':
                value = True
            elif value == 'Выключить':
                value = False
            else:
                raise ValueError('Недопустимое значение')
            field_name = 'friend_place_visible'

        DB.update(cur, table_name='users', field_name=field_name, new_value=value,
                  cond_field_list=['user_id'], cond_value_list=[message.from_user.id])
        con.commit()
        bot.send_message(message.from_user.id, 'Настройка изменена',
                         reply_markup=ReplyKeyboardRemove())
    except ValueError:
        bot.reply_to(message, 'Недопустимое значение')
    except RuntimeError as runtime_err:
        bot.reply_to(message, runtime_err)
    except psycopg2.Error:
        bot.reply_to(message, 'Ошибка при изменении параметров',
                     reply_markup=ReplyKeyboardRemove())
        if con:
            con.rollback()
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE,
                     reply_markup=ReplyKeyboardRemove())
    finally:
        if con:
            con.close()


@bot.message_handler(commands=['search'])
def search(message: Message):
    con = None
    cur = None

    try:
        con = DB.connect()
        cur = con.cursor()
        DB.select(cur, table_name='users', fields_list=['friend_place_visible'],
                  cond_field_list=['user_id'], cond_value_list=[message.from_user.id])
        visible = cur.fetchone()
        if visible is None:
            bot.send_message(message.from_user.id,
                             'Сохраненных мест не найдено')
            return
        visible = visible[0]
        if visible == True:
            cur.execute("SELECT title, id FROM places WHERE user_id IN (SELECT user_id FROM friends WHERE friend_id = %s) OR user_id = %s",
                        (message.from_user.id, message.from_user.id))
        else:
            DB.select(cur, table_name='places', fields_list=['title', 'id'],
                      cond_field_list=['user_id'], cond_value_list=[message.from_user.id])
        places = cur.fetchall()
        if not places or len(places) == 0:
            bot.send_message(message.from_user.id,
                             'Сохраненных мест не найдено')
            return
        title_list = [str(i + 1) + ' ' + places[i][0]
                      for i in range(len(places))]
        keyboard = create_temporary_reply_keyboard(*title_list)
        msg = bot.send_message(message.from_user.id,
                               'Выберите место', reply_markup=keyboard)
        bot.register_next_step_handler(
            msg, search_in_database, places_list=places, title_list=title_list)
    except psycopg2.Error:
        bot.reply_to(message, 'Ошибка при получении списка сохраненных мест',
                     reply_markup=ReplyKeyboardRemove())
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE,
                     reply_markup=ReplyKeyboardRemove())
    finally:
        if con:
            con.close()


def search_in_database(message: Message, places_list, title_list):
    con = None
    cur = None

    try:
        answer = message.text
        if answer not in title_list:
            raise ValueError()
        place_list_id, _ = answer.split(' ', maxsplit=1)
        title, place_id = places_list[int(place_list_id) - 1]

        con = DB.connect()
        cur = con.cursor()
        DB.select(cur, table_name='places', fields_list=[
                  'photo', 'latitude', 'longitude'], cond_field_list=['id'], cond_value_list=[place_id])
        found_place = cur.fetchone()
        photo, latitude, longitude = found_place
        bot.send_message(message.from_user.id, title,
                         reply_markup=ReplyKeyboardRemove())
        if photo:
            bot.send_photo(message.from_user.id, photo=photo)
        if latitude and longitude:
            bot.send_location(message.from_user.id,
                              latitude=latitude, longitude=longitude)
    except psycopg2.Error:
        bot.reply_to(message, 'Ошибка при получении информации о месте',
                     reply_markup=ReplyKeyboardRemove())
    except ValueError:
        bot.reply_to(message, 'Нет информации о месте',
                     reply_markup=ReplyKeyboardRemove())
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE,
                     reply_markup=ReplyKeyboardRemove())
    finally:
        if con:
            con.close()


@bot.message_handler(commands=['delete'])
def delete(message: Message):
    con = None
    cur = None

    try:
        con = DB.connect()
        cur = con.cursor()
        DB.select(cur, table_name='places', fields_list=['title', 'id'], cond_field_list=[
                  'user_id'], cond_value_list=[message.from_user.id])
        places = cur.fetchall()
        if len(places) == 0:
            bot.send_message(message.from_user.id,
                             'Сохраненных мест не найдено')
            return
        title_list = [str(i + 1) + ' ' + places[i][0]
                      for i in range(len(places))]
        keyboard = create_temporary_reply_keyboard(*title_list, 'Отмена')
        msg = bot.send_message(message.from_user.id,
                               'Выберите место', reply_markup=keyboard)
        bot.register_next_step_handler(
            msg, delete_from_database, places_list=places, title_list=title_list)
    except psycopg2.Error:
        bot.reply_to(message, 'Ошибка при получении списка сохраненных мест',
                     reply_markup=ReplyKeyboardRemove())
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE,
                     reply_markup=ReplyKeyboardRemove())
    finally:
        if con:
            con.close()


def delete_from_database(message: Message, places_list, title_list):
    con = None
    cur = None

    try:
        answer = message.text
        if answer == 'Отмена':
            bot.send_message(message.from_user.id, 'Удаление отменено',
                             reply_markup=ReplyKeyboardRemove())
            return
        if answer not in title_list:
            raise ValueError()
        place_list_id, _ = answer.split(' ', maxsplit=1)
        _, place_id = places_list[int(place_list_id) - 1]

        con = DB.connect()
        cur = con.cursor()
        DB.delete(cur, table_name='places', cond_field_list=[
                  'id'], cond_value_list=[place_id])
        con.commit()
        bot.send_message(message.from_user.id, 'Место удалено',
                         reply_markup=ReplyKeyboardRemove())
    except psycopg2.Error:
        bot.reply_to(message, 'Ошибка при удалении',
                     reply_markup=ReplyKeyboardRemove())
        if con:
            con.rollback()
    except ValueError:
        bot.reply_to(message, 'Нет информации о месте',
                     reply_markup=ReplyKeyboardRemove())
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE,
                     reply_markup=ReplyKeyboardRemove())
    finally:
        if con:
            con.close()


@bot.message_handler(commands=['add_friend'])
def add_friend(message: Message):
    try:
        keyboard = create_temporary_reply_keyboard('Отмена')
        msg = bot.send_message(
            message.from_user.id, 'Отправьте контакт друга', reply_markup=keyboard)
        bot.register_next_step_handler(msg, add_friend_to_database)
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE,
                     reply_markup=ReplyKeyboardRemove())


def add_friend_to_database(message: Message):
    con = None
    cur = None

    try:
        if message.text == 'Отмена':
            bot.send_message(
                message.from_user.id, 'Добавление отменено', reply_markup=ReplyKeyboardRemove())
            return

        con = DB.connect()
        cur = con.cursor()

        friend = message.contact
        if not friend:
            raise ValueError('Недопустимое значение')

        if not friend.user_id:
            raise ValueError('Не удается определить id пользователя')

        DB.insert(cur, table_name='users', fields_list=['user_id', 'user_name'], values_list=[
                  message.from_user.id, message.from_user.first_name], conflict_field_list=['user_id'])
        DB.insert(cur, table_name='users', fields_list=['user_id', 'user_name'], values_list=[
                  friend.user_id, friend.first_name], conflict_field_list=['user_id'])
        DB.insert(cur, table_name='friends', fields_list=[
                  'user_id', 'friend_id'], values_list=[message.from_user.id, friend.user_id])
        con.commit()
        bot.send_message(message.from_user.id, 'Друг добавлен',
                         reply_markup=ReplyKeyboardRemove())
    except ValueError as val_err:
        bot.reply_to(message, val_err, reply_markup=ReplyKeyboardRemove())
    except psycopg2.Error as err:
        if con:
            con.rollback()
        if str(err).find('duplicate key value violates unique constraint') != -1:
            bot.reply_to(message, 'Данный друг уже добавлен',
                         reply_markup=ReplyKeyboardRemove())
        else:
            bot.reply_to(message, 'Ошибка при сохранении',
                         reply_markup=ReplyKeyboardRemove())
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE,
                     reply_markup=ReplyKeyboardRemove())
    finally:
        if con:
            con.close()


@bot.message_handler(commands=['delete_friend'])
def delete_friend(message: Message):
    con = None
    cur = None

    try:
        con = DB.connect()
        cur = con.cursor()
        cur.execute("SELECT user_name, friend_id FROM friends JOIN users ON (friends.friend_id = users.user_id) WHERE friends.user_id = %s",
                    (message.from_user.id,))
        friends = cur.fetchall()
        if len(friends) == 0:
            bot.send_message(message.from_user.id,
                             'У вас нет сохраненных друзей')
            return
        friends_name = [str(i + 1) + ' ' + friends[i][0]
                        for i in range(len(friends))]
        keyboard = create_temporary_reply_keyboard(*friends_name, 'Отмена')
        msg = bot.send_message(message.from_user.id,
                               'Выберите друга', reply_markup=keyboard)
        bot.register_next_step_handler(
            msg, delete_friend_from_database, friends_list=friends, friends_name=friends_name)
    except psycopg2.Error:
        bot.reply_to(message, 'Ошибка при получении списка друзей',
                     reply_markup=ReplyKeyboardRemove())
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE,
                     reply_markup=ReplyKeyboardRemove())
    finally:
        if con:
            con.close()


def delete_friend_from_database(message: Message, friends_list, friends_name):
    con = None
    cur = None

    try:
        answer = message.text
        if answer == 'Отмена':
            bot.send_message(message.from_user.id, 'Удаление отменено',
                             reply_markup=ReplyKeyboardRemove())
            return
        if answer not in friends_name:
            raise ValueError()
        friend_list_id, _ = answer.split(' ', maxsplit=1)
        friend_id = friends_list[int(friend_list_id) - 1][1]

        con = DB.connect()
        cur = con.cursor()
        DB.delete(cur, table_name='friends', cond_field_list=[
                  'user_id', 'friend_id'], cond_value_list=[message.from_user.id, friend_id])
        con.commit()
        bot.send_message(message.from_user.id, 'Друг удален',
                         reply_markup=ReplyKeyboardRemove())
    except psycopg2.Error:
        bot.reply_to(message, 'Ошибка при удалении друга',
                     reply_markup=ReplyKeyboardRemove())
        if con:
            con.rollback()
    except ValueError:
        bot.reply_to(message, 'Нет информации о друге',
                     reply_markup=ReplyKeyboardRemove())
    except Exception:
        bot.reply_to(message, ERROR_MESSAGE,
                     reply_markup=ReplyKeyboardRemove())
    finally:
        if con:
            con.close()

@server.route('/' + TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

@server.route("/")
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url='https://geo-note-bot.herokuapp.com/' + TOKEN)
    return "!", 200

bot.enable_save_next_step_handlers(delay=1)
bot.load_next_step_handlers()

if __name__ == "__main__":
    server.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
