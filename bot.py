#!/usr/bin/env python3.8
# -*- coding: utf-8 -*-

# A simple chat client for matrix.
# This sample will allow you to connect to a room, and send/recieve messages.
# Args: host:port username password room
# Error Codes:
# 1 - Unknown problem has occured
# 2 - Could not find the server.
# 3 - Bad URL Format.
# 4 - Bad username/password.
# 11 - Wrong room format.
# 12 - Couldn't find room.

import sys
import logging
import time
import datetime
import json
import os
import pickle
import re
import threading
import random
import requests
import traceback
import vk
import ujson
import wget
import uuid
from PIL import Image

from matrix_client.client import MatrixClient
from matrix_client.api import MatrixRequestError
from requests.exceptions import MissingSchema
from requests import exceptions
import config as conf

client = None
log = None
data={}
lock = None

vk_threads = {}

vk_dialogs = {}

VK_API_VERSION = '5.95'
VK_POLLING_VERSION = '3'

currentchat = {}

chatEquality = {}

def retrieve_vk_message_by_matrix_id(mtxId):
  if mtxId in chatEquality:
    return chatEquality[mtxId]
  else: 
    return None

def retrieve_matrix_message_by_vk_id(vkId):
  result = None
  for mtxId, Id in chatEquality.items():
    if Id == vkId:
      result = mtxId
      break
  return result

def store_vk_message_by_matrix_id(vkId, mtxId):
  chatEquality[mtxId] = vkId

def process_command(user,room,cmd,formated_message=None,format_type=None,reply_to_id=None,file_url=None,file_type=None):
  global client
  global log
  global data
  try:
    log.debug("=start function=")
    answer=None
    session_data_room=None
    session_data_vk=None
    session_data_user=None
    vkReplyTo=None

    if reply_to_id!=None and format_type=="org.matrix.custom.html" and formated_message!=None:
      # разбираем, чтобы получить исходное сообщение и ответ
      vkReplyTo = retrieve_vk_message_by_matrix_id(reply_to_id)
      source_message=re.sub('<mx-reply><blockquote>.*<\/a><br>','', formated_message)
      source_message=re.sub('<mx-reply><blockquote>.*<\/a><br />','', source_message)
      source_message=re.sub('</blockquote></mx-reply>.*','', source_message)
      source_cmd=re.sub(r'.*</blockquote></mx-reply>','', formated_message.replace('\n',''))
      log.debug("source=%s"%source_message)
      log.debug("cmd=%s"%source_cmd)
      if vkReplyTo == None:
        cmd="> %s\n\n%s"%(source_message,source_cmd)
      else:
        cmd=source_cmd

    if re.search('^@%s:.*'%conf.username, user.lower()) is not None:
      # отправленное нами же сообщение - пропускаем:
      log.debug("skip our message")
      return True

    if user not in data["users"]:
      data["users"][user]={}
    if "rooms" not in data["users"][user]:
      data["users"][user]["rooms"]={}
    if "vk" not in data["users"][user]:
      data["users"][user]["vk"]={}
    if room not in data["users"][user]["rooms"]:
      data["users"][user]["rooms"][room]={}
      data["users"][user]["rooms"][room]["state"]="listen_command"

    session_data_room=data["users"][user]["rooms"][room]
    session_data_vk=data["users"][user]["vk"]
    session_data_user=data["users"][user]

    cur_state=data["users"][user]["rooms"][room]["state"]

    log.debug("user=%s send command=%s"%(user,cmd))
    log.debug("cur_state=%s"%cur_state)

    # комната в режиме диалога - это созданная ботом комната. Она не принимает иных команд. Все команды принимает только комната с ботом
    if cur_state == "dialog":
      bot_control_room=data["users"][user]["matrix_bot_data"]["control_room"]
      dialog=session_data_room["cur_dialog"]

      if "pause" in data["users"][user]["rooms"][room]:
        if data["users"][user]["rooms"][room]["pause"]==True:
          # комната в приостановленном режиме - сообщаем, что пересылка отключена:
          if send_notice(room,"Пересылка сообщений из этой комнаты в ВК и обратно приостановлена. Для возобновления используйте команду '!resume %s' в комнате управления ботом\nВаше сообщение не было отправлено в ВК."%room) == False:
            log.error("send_notice")
            return False
          return True

      if file_type!=None and file_url!=None:
        # отправка файла:
        if re.search("^image",file_type)!=None:
          # Отправка изображения из матрицы:
          photo_data=get_file(file_url)
          if photo_data==None:
            log.error("error get file by mxurl=%s"%file_url)
            bot_system_message(user,'Ошибка: не смог получить вложение из матрицы по mxurl=%s'%file_url)
            send_message(room,'Ошибка: не смог получить вложение из матрицы по mxurl=%s'%file_url)
            return False
          message_id=vk_send_photo(session_data_vk["vk_id"],dialog["id"],cmd,photo_data,dialog["type"])
          if message_id == None:
            log.error("error vk_send_photo() for user %s"%user)
            send_message(room,"не смог отправить фото в ВК - ошибка АПИ")
            return False
        elif re.search("^video",file_type)!=None:
          # Отправка видео из матрицы:
          video_data=get_file(file_url)
          if video_data==None:
            log.error("error get file by mxurl=%s"%file_url)
            bot_system_message(user,'Ошибка: не смог получить вложение из матрицы по mxurl=%s'%file_url)
            send_message(room,'Ошибка: не смог получить вложение из матрицы по mxurl=%s'%file_url)
            return False
          message_id=vk_send_video(session_data_vk["vk_id"],dialog["id"],cmd,video_data,dialog["type"])
          if message_id == None:
            log.error("error vk_send_video() for user %s"%user)
            send_message(room,"не смог отправить видео в ВК - ошибка АПИ")
            return False
        elif re.search("^audio",file_type)!=None:
          # Отправка звукового файла из матрицы:
          audio_data=get_file(file_url)
          if audio_data==None:
            log.error("error get file by mxurl=%s"%file_url)
            bot_system_message(user,'Ошибка: не смог получить вложение из матрицы по mxurl=%s'%file_url)
            send_message(room,'Ошибка: не смог получить вложение из матрицы по mxurl=%s'%file_url)
            return False
          message_id=vk_send_doc(session_data_vk["vk_id"],dialog["id"],cmd,audio_data,dialog["type"])
          if message_id == None:
            log.error("error vk_send_doc() for user %s"%user)
            send_message(room,"не смог отправить аудио в ВК - ошибка АПИ")
            return False

        else:
          # Отправка простого файла из матрицы:
          doc_data=get_file(file_url)
          if doc_data==None:
            log.error("error get file by mxurl=%s"%file_url)
            bot_system_message(user,'Ошибка: не смог получить вложение из матрицы по mxurl=%s'%file_url)
            send_message(room,'Ошибка: не смог получить вложение из матрицы по mxurl=%s'%file_url)
            return False
          message_id=vk_send_doc(session_data_vk["vk_id"],dialog["id"],cmd,doc_data,dialog["type"])
          if message_id == None:
            log.error("error vk_send_doc() for user %s"%user)
            send_message(room,"не смог отправить файл в ВК - ошибка АПИ")
            return False
      else:
        # отправка текста:
        message_id=vk_send_text(session_data_vk["vk_id"],dialog["id"],cmd,dialog["type"], None, vkReplyTo)
        if message_id == None:
          log.error("error vk_send_text() for user %s"%user)
          send_message(room,"не смог отправить сообщение в ВК - ошибка АПИ")
          return False

      # Сохраняем message_id, полученный от ВК, когда мы отправили сообщение из матрицы в ВК:
      try:
        log.debug("add last message id as: %d"%message_id)
      except:
        log.error("message_id not int!")
        log.error("message_id=")
        log.error(message_id)
        return False
      if save_message_id(user,room,message_id) == False:
        log.error("save_message_id()")
        bot_system_message(user,'Ошибка: не смог сохранить идентификатор отправленного сообщения - внутренняя ошибка бота')
        return False
      return True

    # Комната управления:
    # в любом состоянии отмена - всё отменяет:
    if re.search('^!stop$', cmd.lower()) is not None or \
        re.search('^!стоп$', cmd.lower()) is not None or \
        re.search('^!отмена$', cmd.lower()) is not None or \
        re.search('^!cancel$', cmd.lower()) is not None:
      data["users"][user]["rooms"][room]["state"]="listen_command"
      send_message(room,'Отменил текущий режим (%s) и перешёл в начальный режим ожидания команд. Жду команд.'%session_data_room["state"])
      # сохраняем на диск:
      save_data(data)
      return True
    elif re.search('^!стат$', cmd.lower()) is not None or \
        re.search('^!состояние$', cmd.lower()) is not None or \
        re.search('^!stat$', cmd.lower()) is not None:
      send_message(room,"Текущее состояние: %s"%session_data_room["state"])
      if session_data_room["state"]=="dialog":
        send_message(room,'Текущая комната: "%s"'%session_data_room["cur_dialog"]["title"])
      return True
    elif re.search('^!ping$', cmd.lower()) is not None:
      message="==== Состояние связи с VK: ====\n"
      message+="Состояние соединения: %s\n"%data["users"][user]["vk"]["connection_status"]
      message+="Описание состояния соединения: %s\n"%data["users"][user]["vk"]["connection_status_descr"]

      delta_ts = int(time.time())-data["users"][user]["vk"]["ts_check_poll"]
      message+="Время прошедшее с предыдущего опроса событий в ВК: %d сек.\n"%delta_ts
      send_message(room,message)
      return True
    elif re.search('^!reconnect$', cmd.lower()) is not None:
      data["users"][user]["vk"]["exit"]=True
      message="Послал команду на переподключение к ВК.\n"
      send_message(room,message)
      return True

    if cur_state == "listen_command":
      if re.search('^!*\?$', cmd.lower()) is not None or \
        re.search('^!*h$', cmd.lower()) is not None or \
        re.search('^!*помощь', cmd.lower()) is not None or \
        re.search('^!*справка', cmd.lower()) is not None or \
        re.search('^!*help', cmd.lower()) is not None:
        answer="""!login - авторизоваться в ВК
  !logout - выйти из ВК (пока не реализовано)
  !search - поиск диалогов в ВК (пока не реализовано)
  !dialogs - список всех ваших диалогов в ВК. В ответном сообщении Вам потребуется ввести номер диалога, чтобы начать общение в этом диалоге через матрицу.
  !rooms - список соответствий диалогов ВК и ваших комнат
  !delete room_id - удалить соответствение диалога ВК и комнаты MATRIX. Диалог в ВК останется и если придёт новое сообщение в нём - то бот заново создаст у вас комнту и соответстие. И вы получите сообщение из ВК.
  !pause room_id - приостановить пересылку сообщений из ВК в указанную комнату MATRIX. Для включения используейте команду !resume room_id.
  !resume room_id - возобновить пересылку сообщений из ВК в указанную комнату MATRIX. Для приостановки используейте команду !pause room_id.
  !stat - текущее состояние комнаты
  !reconnect - переподключиться к ВК
  !ping - текущее состояние соединения с ВК
        """ 
        return send_message(room,answer)

      # login
      elif re.search('^!login$', cmd.lower()) is not None:
        return login_command(user,room,cmd)
      # dialogs
      elif re.search('^!dialogs$', cmd.lower()) is not None or \
        re.search('^!диалоги$', cmd.lower()) is not None or \
        re.search('^!d$', cmd.lower()) is not None:
        return dialogs_command(user,room,cmd)

      elif re.search('^!rooms$', cmd.lower()) is not None or \
        re.search('^!комнаты$', cmd.lower()) is not None:
        return rooms_command(user,room,cmd)

      elif re.search('^!delete .*', cmd.lower()) is not None:
        return delete_room_association(user,room,cmd)

      elif re.search('^!pause .*', cmd.lower()) is not None:
        return bridge_pause_for_room(user,room,cmd)

      elif re.search('^!resume .*', cmd.lower()) is not None:
        return bridge_resume_for_room(user,room,cmd)

      elif re.search('^!rooms$', cmd.lower()) is not None or \
        re.search('^!комнаты$', cmd.lower()) is not None:
        return rooms_command(user,room,cmd)

    elif cur_state == "wait_vk_id":
      # парсинг ссылки
      m = re.search('https://oauth\.vk\.com/blank\.html#access_token=[a-z0-9]*&expires_in=[0-9]*&user_id=[0-9]*',cmd)
      if m:
        code = extract_unique_code(m.group(0))
        try:
          vk_user = verifycode(code)
        except:
          send_message(room, 'Неверная ссылка, попробуйте ещё раз!')
          log.warning("error auth url from user=%s"%user)
          return False
        send_message(room,'Вход выполнен в аккаунт {} {}!'.format(vk_user['first_name'], vk_user['last_name']))
        data["users"][user]["vk"]["vk_id"]=code
        data["users"][user]["vk"]["first_name"]=vk_user['first_name']
        data["users"][user]["vk"]["last_name"]=vk_user['last_name']
        data["users"][user]["rooms"][room]["state"]="listen_command"
        # сохраняем на диск:
        save_data(data)

    elif cur_state == "wait_vk_app_id":
      # парсинг ссылки
      try:
        vk_app_id = int(cmd)
      except:
        log.warning("error get VK app id from user=%s"%user)
        send_message(room, 'Я ожидаю от вас "ID приложения" по ссылке https://vk.com/apps?act=manage в настройках созданного Вами приложения. Код должен быть обычным числом. Или же отмените ожидание с помощью команд: !стоп, !stop, !отмена, !cancel')
        return False
      data["users"][user]["vk"]["vk_app_id"]=vk_app_id
      data["users"][user]["rooms"][room]["state"]="listen_command"
      # сохраняем на диск:
      save_data(data)
      # заново запускаем обработчик логина с уже обновлёнными данными:
      return login_command(user,room,cmd)

    elif cur_state == "wait_dialog_index":
      try:
        index=int(cmd)
      except:
        send_message(room,"пожалуйста, введите номер диалога или команды !stop, !отмена, !cancel")
        return True
      if index not in session_data_room["dialogs_list"]:
        send_message(room,"Неверный номер диалога, введите верный номер диалога или команды !stop, !отмена, !cancel")
        return True
      cur_dialog=session_data_room["dialogs_list"][index]
      found_room=find_bridge_room(user,cur_dialog["id"])
      if found_room != None:
        # Такая комната уже существует!
        log.info("room already exist for user '%s' for vk-dialog with vk-id '%d' ('%s')"%(user,cur_dialog["id"],cur_dialog["title"]))
        send_message(room,"У Вас уже есть комната (%s), связанная с этим пользователем - не создаю повторную. Позже будет добавлен функционал по чистке такх комнат."%found_room)
        send_message(room,"Перешёл в режим команд")
        data["users"][user]["rooms"][room]["state"]="listen_command"
        return False

      # получаем фото пользователя ВК с которым устанавливаем мост:
      room_avatar_mx_url=None
      vk_id=data["users"][user]["vk"]["vk_id"]
      session = get_session(vk_id)
      user_photo_url=vk_get_user_photo_url(session, cur_dialog["id"])
      if user_photo_url==None:
        log.error("get user vk profile photo for user_id=%d"%cur_dialog["id"])
      else:
        user_photo_image_data=get_data_from_url(user_photo_url)
        if user_photo_image_data==None:
          log.error("get image from url: %s"%user_photo_url)
           
      room_id=create_room(user,cur_dialog["title_ext"] + " (VK)",user_photo_image_data)
      if room_id==None:
        log.error("error create_room() for user '%s' for vk-dialog with vk-id '%d' ('%s')"%(user,cur_dialog["id"],cur_dialog["title"]))
        send_message(room,"Не смог создать дополнительную комнату в матрице: '%s' связанную с одноимённым диалогом в ВК"%cur_dialog["title"])
        send_message(room,"Перешёл в режим команд")
        data["users"][user]["rooms"][room]["state"]="listen_command"
        return False
      send_message(room,"Создал новую комнату матрицы с именем: '%s (VK)' связанную с одноимённым диалогом в ВК"%cur_dialog["title"])
      data["users"][user]["rooms"][room_id]={}
      data["users"][user]["rooms"][room_id]["last_matrix_owner_message"]=[]
      data["users"][user]["rooms"][room_id]["cur_dialog"]=cur_dialog
      data["users"][user]["rooms"][room_id]["state"]="dialog"
      # сохраняем на диск:
      save_data(data)
      send_message(room,"Перешёл в режим команд")
      data["users"][user]["rooms"][room]["state"]="listen_command"
    return True
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute process_command()")
    bot_system_message(user,"внутренняя ошибка бота при обработке команды в функции process_command()")
    return False

# сохраняем message_id в списке отправленных нами сообщений:
def save_message_id(user,room,message_id):
  global log
  global data
  try:
    # уточнение типа:
    if isinstance(data["users"][user]["rooms"][room]["last_matrix_owner_message"], list) == False:
      data["users"][user]["rooms"][room]["last_matrix_owner_message"]=[]
    cur_m_list=data["users"][user]["rooms"][room]["last_matrix_owner_message"]
    cur_m_list.append(message_id)
    # ограничиваем список запомненных сообщений 30-ю:
    s=len(cur_m_list)
    if s > 30:
      delta=s-30
      cur_m_list=cur_m_list[delta:]
    data["users"][user]["rooms"][room]["last_matrix_owner_message"]=cur_m_list
  except:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute save_message_id()")
    return False
  return True

# проверяем наличие message_id в списке ранее отправленных нами сообщений:
def check_own_message_id(user,room,message_id):
  global log
  global data
  try:
    # уточнение типа:
    if isinstance(data["users"][user]["rooms"][room]["last_matrix_owner_message"], list) == False:
      data["users"][user]["rooms"][room]["last_matrix_owner_message"]=[]
    if message_id in data["users"][user]["rooms"][room]["last_matrix_owner_message"]:
      return True
    else:
      return False
  except:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute check_own_message_id()")
    return False

def update_user_info(user):
  global log
  global data

  found=False
  try:
    log.debug("=start function=")
    #try:
    vk_id=data["users"][user]["vk"]["vk_id"]
    session = get_session(vk_id)
    api = vk.API(session, v=VK_API_VERSION)
    user_profile=dict(api.account.getProfileInfo(fields=[]))
    data["users"][user]["vk"]["first_name"]=user_profile['first_name']
    data["users"][user]["vk"]["last_name"]=user_profile['last_name']
    dialogs=get_dialogs(vk_id)
    if dialogs == None:
      log.error("get_dialogs() for user=%s"%user)
      bot_system_message(user,"внутренняя ошибка бота при получении списка диалогов пользователя в функции update_user_info()")
      return False
    # ищем свой аккаунт по ФИО (иначе пока не знаю как получить свой ID):
    for user_id in dialogs["users"]:
      item=dialogs["users"][user_id]
      if item["last_name"] == data["users"][user]["vk"]["last_name"] and \
        item["first_name"] == data["users"][user]["vk"]["first_name"]:
        # предполагаем, что у пользователя в контактах не будет человека с таким же ФИО, как и он сам O_o:
        found=True
        data["users"][user]["vk"]["user_id"]=item["id"]
    if found==True:
      log.info("определил свой аккаунт как: %s %s, id:%d"%(\
        data["users"][user]["vk"]["last_name"],\
        data["users"][user]["vk"]["first_name"],\
        data["users"][user]["vk"]["user_id"]\
        ))
      save_data(data)
      return True
    else:
      log.warning("не нашли информацию о себе - пропуск")
      return False
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute update_user_info()")
    bot_system_message(user,"внутренняя ошибка бота при получении профиля пользователя в функции update_user_info()")
    return False

def find_bridge_room(user,vk_room_id):
  global log
  try:
    log.debug("=start function=")
    for room in data["users"][user]["rooms"]:
      if data["users"][user]["rooms"][room]["state"]=="dialog" and \
         data["users"][user]["rooms"][room]["cur_dialog"]["id"]==vk_room_id:
        log.info("found bridge for user '%s' with vk_id '%d'"%(user,vk_room_id))
        return room;
    return None
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute find_bridge_room()")
    bot_system_message(user,"внутренняя ошибка бота в функции find_bridge_room()")
    return None

def get_new_vk_messages_v2(user):
  global data
  global lock
  global log
  try:
    log.debug("=start function=")
    if "vk" not in data["users"][user]:
      return None
    if "vk_id" not in data["users"][user]["vk"]:
      return None
    server=""
    key=""
    session=""
    ts=0
    log.debug("try lock() before access global data()")
    with lock:
      log.debug("success lock() before access global data")
      if "server" in data["users"][user]["vk"]:
        server=data["users"][user]["vk"]["server"]
      if "ts_polling" in data["users"][user]["vk"]:
        ts=data["users"][user]["vk"]["ts_polling"]
      if "key" in data["users"][user]["vk"]:
        key=data["users"][user]["vk"]["key"]
    log.debug("release lock() after access global data")
    exit_flag=False

    while True:

      try:
        if server=="" or key=="":
          log.warning('Need update server data')
          raise Exception('Need update server data')
        log.debug("get polling with ts=%d"%ts)
        url="https://%(server)s?act=a_check&key=%(key)s&ts=%(ts)s&wait=25&mode=2&version=%(VK_POLLING_VERSION)s"%\
          {\
            "ts":ts,\
            "key":key,\
            "server":server,\
            "VK_POLLING_VERSION":VK_POLLING_VERSION\
          }
        log.debug("try exec requests.post(%s)"%url)
        r = requests.post(url,timeout=conf.post_timeout)
        log.debug("requests.post return: %s"%r.text)
        ret=json.loads(r.text)
        if "failed" in ret and ( ret["failed"]==2 or ret["failed"]==3):
          log.info("need update key or ts")
          raise Exception("need update key or ts")

        if "updates" not in ret:
          log.warning("'No 'updates' in ret'")
          raise Exception("No 'updates' in ret")
        ts=ret["ts"]
        log.debug("try lock() before access global data()")
        with lock:
          log.debug("success lock() before access global data")
          data["users"][user]["vk"]["ts_polling"]=ts
          data["users"][user]["vk"]["ts_check_poll"]=int(time.time())
        log.debug("release lock() after access global data")
        #log.debug("ret=")
        #log.debug(json.dumps(ret, indent=4, sort_keys=True,ensure_ascii=False))
      except (exceptions.ConnectionError, TimeoutError, exceptions.Timeout, \
          exceptions.ConnectTimeout, exceptions.ReadTimeout) as e:
        log.debug("except timeout from requests.post(): %s"%e)

        # Проверка на необходимость выйти из потока:
        exit_flag=False
        log.debug("try lock() before access global data()")
        with lock:
          log.debug("success lock() before access global data")
          if "exit" in data["users"][user]["vk"]:
            exit_flag=data["users"][user]["vk"]["exit"]
        log.debug("release lock() after access global data")
        log.debug("thread: exit_flag=%d"%int(exit_flag))
        if exit_flag==True:
          log.info("get command to close thread for user %s - exit from thread..."%user)
          return None
        log.debug("try again requests.post()")
        continue

      except Exception as e:
        log.debug("except from requests.post()")
        log.debug("e=")
        log.debug(e)

        # Проверка на необходимость выйти из потока:
        exit_flag=False
        log.debug("try lock() before access global data()")
        with lock:
          log.debug("success lock() before access global data")
          if "exit" in data["users"][user]["vk"]:
            exit_flag=data["users"][user]["vk"]["exit"]
        log.debug("release lock() after access global data")
        log.debug("thread: exit_flag=%d"%int(exit_flag))
        if exit_flag==True:
          log.info("get command to close thread for user %s - exit from thread..."%user)
          return None

        log.warning("error get event updates - try update session info")
        session = get_session(data["users"][user]["vk"]["vk_id"])
        log.debug("session=")
        log.debug(session)
        log.debug("try exec get_tses()")
        ts,pts,key,server=get_tses(session)
        log.debug("end exec get_tses()")
        log.debug("try lock() before access global data()")
        with lock:
          log.debug("success lock() before access global data")
          update_vk_tses_data(data,user,ts,pts,key,server)
          save_data(data)
        log.debug("release lock() after access global data")

        # продолжаем попытки получения данных от vk
        log.debug("try again requests.post()")
        continue

      # ищем нужные нам события (новые сообщения), типы всех событий описаны вот тут: https://vk.com/dev/using_longpoll_2
      # 4 - Добавление нового сообщения. 
      # 5 - Редактирование сообщения. 
      # 51 - Один из параметров (состав, тема) беседы $chat_id были изменены. $self — 1 или 0 (вызваны ли изменения самим пользователем). 
      # 52 - Изменение информации чата $peer_id с типом $type_id, $info — дополнительная информация об изменениях, зависит от типа события.
      ts=ret["ts"]
      new_events=False
      for update in ret["updates"]:
        if update[0]==4 \
          or update[0]==5 \
          or update[0]==51 \
          or update[0]==52:
          new_events=True
          log.info("getting info about new events - try get events...")
          break
      if new_events:
        # выходим из цикла ожидания событий:
        break

      # Проверка на необходимость выйти из потока:
      exit_flag=False
      log.debug("try lock() before access global data()")
      with lock:
        log.debug("success lock() before access global data")
        if "exit" in data["users"][user]["vk"]:
          exit_flag=data["users"][user]["vk"]["exit"]
      log.debug("release lock() after access global data")
      log.debug("thread: exit_flag=%d"%int(exit_flag))
      if exit_flag==True:
        log.info("get command to close thread for user %s - exit from thread..."%user)
        return None


    # Проверка на необходимость выйти из потока:
    exit_flag=False
    log.debug("try lock() before access global data()")
    with lock:
      log.debug("success lock() before access global data")
      if "exit" in data["users"][user]["vk"]:
        exit_flag=data["users"][user]["vk"]["exit"]
    log.debug("release lock() after access global data")
    log.debug("thread: exit_flag=%d"%int(exit_flag))
    if exit_flag==True:
      log.info("get command to close thread for user %s - exit from thread..."%user)
      return None

    # получаем данные событий:
    log.debug("session=")
    log.debug(session)
    session = get_session(data["users"][user]["vk"]["vk_id"])
    log.debug("session=")
    log.debug(session)

    api = vk.API(session, v=VK_API_VERSION)
    try:
      #ts_pts = ujson.dumps({"ts": data["users"][user]["vk"]["ts"], "pts": data["users"][user]["vk"]["pts"]})
      #ts_pts = ujson.dumps({"ts": data["users"][user]["vk"]["ts"], "pts": data["users"][user]["vk"]["pts"],"wait":25})
      #new = api.execute(code='return API.messages.getLongPollHistory({});'.format(ts_pts))
      log.debug("try exec api.messages.getLongPollHistory()")
      new = api.messages.getLongPollHistory(
          ts=data["users"][user]["vk"]["ts_polling"],\
          pts=data["users"][user]["vk"]["pts"],\
          lp_version=VK_POLLING_VERSION\
        )
      log.debug("end exec api.messages.getLongPollHistory()")
    except vk.api.VkAPIError:
      timeout = 3
      log.warning('Retrying getLongPollHistory in {} seconds'.format(timeout))
      time.sleep(timeout)
      ts,pts,key,server=get_tses(session)
      log.debug("try lock() before access global data()")
      with lock:
        log.debug("success lock() before access global data")
        update_vk_tses_data(data,user,ts,pts,key,server)
      log.debug("release lock() after access global data")
      log.debug("try exec api.messages.getLongPollHistory()")
      new = api.messages.getLongPollHistory(
          ts=ts,\
          pts=pts,\
          lp_version=VK_POLLING_VERSION\
        )
      log.debug("end exec api.messages.getLongPollHistory()")

    log.debug("New data from VK:")
    log.debug(json.dumps(new, indent=4, sort_keys=True,ensure_ascii=False))

    msgs = new['messages']
    log.debug("try lock() before access global data()")
    with lock:
      log.debug("success lock() before access global data")
      data["users"][user]["vk"]["pts"] = new["new_pts"]
    log.debug("release lock() after access global data")
    count = msgs["count"]

    res = None
    if count == 0:
      pass
    else:
      res={}
      res["messages"] = msgs["items"]
      # при разговоре с админами иногда может не быть профилей O_o
      if "profiles" in new:
        res["profiles"] = new["profiles"]
      else:
        res["profiles"] = []
      res["conversations"] = new["conversations"]
    return res

  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute get_new_vk_messages_v2()")
    bot_system_message(user,"ошибка получения сообщений из ВК. Ошибка работы с ВК-апи в функции get_new_vk_messages_v2()")
    return None

def get_new_vk_messages(user):
  global data
  global lock
  global log
  try:
    log.debug("=start function=")
    if "vk" not in data["users"][user]:
      return None
    if "vk_id" not in data["users"][user]["vk"]:
      return None
    session = get_session(data["users"][user]["vk"]["vk_id"])

    #log.debug("ts=%d, pts=%d"%(data["users"][user]["vk"]["ts"], data["users"][user]["vk"]["pts"]))

    api = vk.API(session, v=VK_API_VERSION)
    try:
      ts_pts = ujson.dumps({"ts": data["users"][user]["vk"]["ts"], "pts": data["users"][user]["vk"]["pts"]})
      #ts_pts = ujson.dumps({"ts": data["users"][user]["vk"]["ts"], "pts": data["users"][user]["vk"]["pts"],"wait":25})
      new = api.execute(code='return API.messages.getLongPollHistory({});'.format(ts_pts))
    except vk.api.VkAPIError:
      timeout = 3
      log.warning('Retrying getLongPollHistory in {} seconds'.format(timeout))
      time.sleep(timeout)
      log.debug("try lock() before access global data()")
      ts,pts,key,server=get_tses(session)
      with lock:
        log.debug("success lock() before access global data")
        update_vk_tses_data(data,user,ts,pts,key,server)
      log.debug("release lock() after access global data")
      ts_pts = ujson.dumps({"ts": data["users"][user]["vk"]["ts"], "pts": data["users"][user]["vk"]["pts"]})
      new = api.execute(code='return API.messages.getLongPollHistory({});'.format(ts_pts))

    log.debug("New data from VK:")
    log.debug(json.dumps(new, indent=4, sort_keys=True,ensure_ascii=False))

    msgs = new['messages']
    log.debug("try lock() before access global data()")
    with lock:
      log.debug("success lock() before access global data")
      data["users"][user]["vk"]["pts"] = new["new_pts"]
    log.debug("release lock() after access global data")
    count = msgs["count"]

    res = None
    if count == 0:
      pass
    else:
      res={}
      res["messages"] = msgs["items"]
      res["profiles"] = new["profiles"]
      res["conversations"] = new["conversations"]
    return res
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute get_new_vk_messages()")
    bot_system_message(user,"ошибка получения сообщений из ВК. Ошибка работы с ВК-апи в функции get_new_vk_messages()")
    return None


def extract_unique_code(text):
  global log
  log.debug("=start function=")
  # Extracts the unique_code from the sent /start command.
  try:
    return text[45:].split('&')[0]
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    return None

def get_session(token):
  global log
  log.debug("=start function=")
  return vk.Session(access_token=token)

def update_vk_tses_data(data, user, ts, pts, key, server):
  data["users"][user]["vk"]["server"]=server
  data["users"][user]["vk"]["key"]=key
  data["users"][user]["vk"]["ts_polling"]=ts
  data["users"][user]["vk"]["pts"]=pts

def get_tses(session):
  global log
  try:
    log.debug("=start function=")
    api = vk.API(session, v=VK_API_VERSION)
    ts = api.messages.getLongPollServer(need_pts=1,v=VK_API_VERSION,lp_version=VK_POLLING_VERSION)
    return ts['ts'], ts['pts'], ts['key'], ts['server']
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute get_tses()")
    return None

def verifycode(code):
  global log
  try:
    log.debug("=start function=")
    session = vk.Session(access_token=code)
    api = vk.API(session, v=VK_API_VERSION)
    return dict(api.account.getProfileInfo(fields=[]))
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute get_user_profile_by_uid()()")
    return None


def info_extractor(info):
  global log
  try:
    log.debug("=start function=")
    info = info[-1].url[8:-1].split('.')
    return info
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute info_extractor()")
    return None

def vk_send_text(vk_id, chat_id, message, chat_type="user", forward_messages=None, replyTo=None):
  global log
  message_id=None
  try:
    log.debug("=start function=")
    random_id=random.randint(0,4294967296)
    session = get_session(vk_id)
    api = vk.API(session, v=VK_API_VERSION)
    if chat_type!="user":
      message_id=api.messages.send(peer_id=chat_id, random_id=random_id,  message=message, forward_messages=forward_messages, reply_to=replyTo)
    else:
      message_id=api.messages.send(user_id=chat_id, random_id=random_id, message=message, forward_messages=forward_messages, reply_to=replyTo)
    # message_id содержит ID отправленного сообщения
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute vk_send_text()")
    log.error("vk_send_text API or network error")
    return None
  return message_id

def vk_send_video(vk_id, chat_id, name, video_data, chat_type="user"):
  global log
  message_id=None
  try:
    log.debug("=start function=")
    random_id=random.randint(0,4294967296)
    session = get_session(vk_id)
    api = vk.API(session, v=VK_API_VERSION)
    # получаем адрес загрузки:
    save_response=api.video.save(name=name)
    log.debug("api.video.save return:")
    log.debug(save_response)
    url = save_response['upload_url']
    files = {'video_file': (name,video_data,'multipart/form-data')}
    r = requests.post(url, files=files, timeout=conf.post_files_timeout)
    log.debug("requests.post return: %s"%r.text)
    ret=json.loads(r.text)
    attachment_str="video%d_%d"%(ret['owner_id'],ret['video_id'])
    if chat_type!="user":
      message_id=api.messages.send(chat_id=chat_id, random_id=random_id, message=name,attachment=(attachment_str))
    else:
      message_id=api.messages.send(user_id=chat_id, random_id=random_id, message=name,attachment=(attachment_str))
    log.debug("api.messages.send return:")
    log.debug(message_id)
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute vk_send_video()")
    log.error("vk_send_video API or network error")
    return None
  return message_id

def vk_send_audio(vk_id, chat_id, name, audio_data, chat_type="user"):
  global log
  message_id=None
  try:
    log.debug("=start function=")
    random_id=random.randint(0,4294967296)
    session = get_session(vk_id)
    api = vk.API(session, v=VK_API_VERSION)
    # получаем адрес загрузки:
    save_response=api.video.save(name=name)
    log.debug("api.video.save return:")
    log.debug(save_response)
    url = save_response['upload_url']

    files = {'video_file': (name,video_data,'multipart/form-data')}
    r = requests.post(url, files=files, timeout=conf.post_files_timeout)
    log.debug("requests.post return: %s"%r.text)
    ret=json.loads(r.text)
    attachment_str="video%d_%d"%(ret['owner_id'],ret['video_id'])
    if chat_type!="user":
      message_id=api.messages.send(chat_id=chat_id, random_id=random_id, message=name,attachment=(attachment_str))
    else:
      message_id=api.messages.send(user_id=chat_id, random_id=random_id, message=name,attachment=(attachment_str))
    log.debug("api.messages.send return:")
    log.debug(message_id)
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute vk_send_audio()")
    log.error("vk_send_video API or network error")
    return None
  return message_id

def vk_send_doc(vk_id, chat_id, name, doc_data, chat_type="user"):
  global log
  message_id=None
  try:
    log.debug("=start function=")
    random_id=random.randint(0,4294967296)
    session = get_session(vk_id)
    api = vk.API(session, v=VK_API_VERSION)
    # получаем адрес загрузки:
    response=api.docs.getMessagesUploadServer()
    log.debug("api.docs.getMessagesUploadServer return:")
    log.debug(response)
    # 
    url = response['upload_url']
    files = {'file': (name,doc_data,'multipart/form-data')}
    r = requests.post(url, files=files, timeout=conf.post_files_timeout)
    log.debug("requests.post return: %s"%r.text)
    ret=json.loads(r.text)
    response=api.docs.save(file=ret['file'],title=name)
    log.debug("api.docs.save return:")
    log.debug(response)
    attachment_str="doc%d_%d"%(response['doc']['owner_id'],response['doc']['id'])
    if chat_type!="user":
      message_id=api.messages.send(chat_id=chat_id,random_id=random_id, message=name,attachment=(attachment_str))
    else:
      message_id=api.messages.send(user_id=chat_id,random_id=random_id, message=name,attachment=(attachment_str))
    log.debug("api..messages.send return:")
    log.debug(message_id)
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute vk_send_doc()")
    log.error("vk_send_doc API or network error")
    return None
  return message_id

def vk_send_photo(vk_id, chat_id, name, photo_data, chat_type="user"):
  global log
  message_id=None
  log.debug("=start function=")
  random_id=random.randint(0,4294967296)
  try:
    session = get_session(vk_id)
    api = vk.API(session, v=VK_API_VERSION)
    # получаем адрес загрузки:
    response=api.photos.getMessagesUploadServer()
    log.debug("api.photos.getMessagesUploadServer return:")
    log.debug(response)
    # 
    url = response['upload_url']
    files = {'photo': ('photo.png',photo_data,'multipart/form-data')}
    r = requests.post(url, files=files, timeout=conf.post_files_timeout)
    log.debug("requests.post return: %s"%r.text)
    ret=json.loads(r.text)
    response=api.photos.saveMessagesPhoto(photo=ret['photo'],server=ret['server'],hash=ret['hash'])
    log.debug("api.photos.saveMessagesPhoto return:")
    log.debug(response)
    attachment="photo%(owner_id)d_%(media_id)d"%{"owner_id":response[0]["owner_id"],"media_id":response[0]["id"]}
    log.debug("attachment=%s"%attachment)
    if chat_type!="user":
      message_id=api.messages.send(chat_id=chat_id, random_id=random_id, message=name,attachment=attachment)
    else:
      message_id=api.messages.send(user_id=chat_id, random_id=random_id, message=name,attachment=attachment)
    log.debug("api..messages.send return:")
    log.debug(message_id)
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute vk_send_photo()")
    log.error("vk_send_photo API or network error")
    return None
  return message_id

def bridge_pause_for_room(user,room,cmd):
  global log
  log.debug("=start function=")
  global lock
  global data
  global client
  try:
    room_id=cmd.replace("!pause ","").strip()
    if room_id in data["users"][user]["rooms"]:
      # приостанавливаем пересылку сообщений из ВК в эту комнату:
      log.info("!pause for room: '%s' for user '%s'"%(room_id,user))
      vk_dialog_title=""
      if "cur_dialog" in data["users"][user]["rooms"][room_id] and \
        "title" in data["users"][user]["rooms"][room_id]["cur_dialog"]:
        vk_dialog_title=data["users"][user]["rooms"][room_id]["cur_dialog"]["title"]
      data["users"][user]["rooms"][room_id]["pause"]=True
      log.info("save state data on disk")
      save_data(data)
      bot_system_message(user,"Успешно приостановил пересылку сообщений из ВК в соответствии: %s - %s"%(vk_dialog_title,room_id))
      if send_notice(room_id,"Пересылка сообщений из ВК в эту комнату приостановлена. Для возобновления используйте команду '!resume %s' в комнате управления ботом"%room_id) == False:
        log.error("send_notice")
    else:
      bot_system_message(user,"Ошибка! Неизвестная комната: %s"%room_id)
      return False
    return True
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute bridge_pause_for_room()")
    bot_system_message(user,"внутренняя ошибка бота")
    return False

def bridge_resume_for_room(user,room,cmd):
  global log
  log.debug("=start function=")
  global lock
  global data
  global client
  try:
    room_id=cmd.replace("!resume ","").strip()
    if room_id in data["users"][user]["rooms"]:
      # возобновляем пересылку сообщений из ВК в эту комнату:
      log.info("!resume for room: '%s' for user '%s'"%(room_id,user))
      vk_dialog_title=""
      if "cur_dialog" in data["users"][user]["rooms"][room_id] and \
        "title" in data["users"][user]["rooms"][room_id]["cur_dialog"]:
        vk_dialog_title=data["users"][user]["rooms"][room_id]["cur_dialog"]["title"]
      data["users"][user]["rooms"][room_id]["pause"]=False
      log.info("save state data on disk")
      save_data(data)
      bot_system_message(user,"Успешно возобновил пересылку сообщений из ВК в соответствии: %s - %s"%(vk_dialog_title,room_id))
      if send_notice(room_id,"Пересылка сообщений из ВК в эту комнату возобновлена. Для приостановки используйте команду '!pause %s' в комнате управления ботом"%room_id) == False:
        log.error("send_notice")
    else:
      bot_system_message(user,"Ошибка! Неизвестная комната: %s"%room_id)
      return False
    return True
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute bridge_resume_for_room()")
    bot_system_message(user,"внутренняя ошибка бота")
    return False

def delete_room_association(user,room,cmd):
  global log
  log.debug("=start function=")
  global lock
  global data
  global client
  try:
    room_id=cmd.replace("!delete ","").strip()
    if room_id in data["users"][user]["rooms"]:
      # удаляем запись об этой комнате из данных:
      log.info("Remove room: '%s' from data of user '%s'"%(room_id,user))
      vk_dialog_title=""
      if "cur_dialog" in data["users"][user]["rooms"][room_id] and \
        "title" in data["users"][user]["rooms"][room_id]["cur_dialog"]:
        vk_dialog_title=data["users"][user]["rooms"][room_id]["cur_dialog"]["title"]
      del data["users"][user]["rooms"][room_id]
      log.info("save state data on disk")
      save_data(data)
      bot_system_message(user,"Успешно удалил соответствие: %s - %s"%(vk_dialog_title,room_id))
      try:
        # удаляем всех остальных из комнаты:
        log.info("kick all from room: '%s'"%(room_id))
        log.debug("members: ",client.rooms[room_id]._members)
        my_full_id=client.user_id
        for item in client.rooms[room_id]._members:
          if item.user_id!=my_full_id:
            log.debug("kick user_id: %s"%item.user_id)
            client.rooms[room_id].kick_user(item.user_id,"пользователь удалил эту ассоциацию диалога ВК и комнаты MATRIX")
      except Exception as e:
        log.error(get_exception_traceback_descr(e))
        log.error("error kick users from room: '%s'"%(room_id))
        bot_system_message(user,"Ошибка при попытке выгнать пользователей из комнаты: %s"%room_id)
      bot_system_message(user,"Успешно выгнал всех из комнаты: %s"%room_id)
      time.sleep(3)
      try:
        # Нужно выйти из комнаты:
        log.info("try leave from room: '%s'"%(room_id))
        response = client.api.leave_room(room_id)
      except Exception as e:
        log.error(get_exception_traceback_descr(e))
        log.error("error leave room: '%s'"%(room_id))
        bot_system_message(user,"Ошибка выхода из комнаты: %s"%room_id)
        return False
      bot_system_message(user,"Успешно вышел из комнаты: %s"%room_id)
      try:
        # И забыть её:
        log.info("Forgot room: '%s'"%(room_id))
        response = client.api.forget_room(room_id)
      except Exception as e:
        log.error(get_exception_traceback_descr(e))
        log.error("error forgot room: '%s'"%(room_id))
        bot_system_message(user,"Не смог 'забыть' (удалить из архива) комнату: %s"%room_id)
        return False
      bot_system_message(user,"Успешно забыл комнату: %s"%room_id)
      log.info("success delete room association for room_id: %s"%room_id)
    else:
      bot_system_message(user,"Не нашёл соответствия с идентификатором комнаты: %s"%room_id)
      bot_cancel_command(room,user)
      return False
    return True
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute delete_room_association()")
    bot_system_message(user,"внутренняя ошибка бота")
    return False

def rooms_command(user,room,cmd):
  global log
  log.debug("=start function=")
  global lock
  global data
  message="=== Список текущих соответствий диалогов ВК и комнат MATRIX: ===\n\n"
  index=1
  try:
    for room_id in data["users"][user]["rooms"]:
      item=data["users"][user]["rooms"][room_id]
      if "cur_dialog" in item:
        message+="%d"%index
        message+=". " + item["cur_dialog"]["title"] + " - " + room_id
        if "pause" in item:
          if item["pause"]==True:
            message+=" (пересылка приостановлена)"
        message+="\n"
        index+=1
      else:
        log.debug("no cur_dialog for room: %s"%room_id)
    bot_system_message(user,message)
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("create and send list of current rooms")
    bot_system_message(user,"Ошибка формирования списка комнат")
    return False
  return True

def dialogs_command(user,room,cmd):
  global log
  global lock
  global data
  try:
    log.debug("=start function=")
    log.debug("dialogs_command()")
    session_data_room=data["users"][user]["rooms"][room]
    session_data_vk=data["users"][user]["vk"]
    if "vk_id" not in session_data_vk or session_data_vk["vk_id"]==None:
      send_message(room,'Вы не вошли в ВК - используйте !login для входа')
      return True
    vk_id=session_data_vk["vk_id"]
    dialogs=get_dialogs(vk_id)
    if dialogs == None:
      send_message(room,'Не смог получить список бесед из ВК - попробуйте позже :-(')
      bot_system_message(user,'Не смог получить список бесед из ВК - попробуйте позже :-(')
      log.error("get_dialogs() for user=%s"%user)
      bot_cancel_command(room,user)
      return False

    # Формируем список диалогов:
    send_message(room,"Выберите диалог:")
    message=""
    index=1
    dialogs_list={}
    for item_id in dialogs["chats"]:
      item=dialogs["chats"][item_id]
      dialogs_list[index]=item
      message+="%d. "%index
      #log.debug(item)
      message+=item["title_ext"]
      message+="\n"
      index+=1
    send_message(room,message)
    data["users"][user]["rooms"][room]["state"]="wait_dialog_index"
    data["users"][user]["rooms"][room]["dialogs_list"]=dialogs_list
    return True
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("create message with dialogs")
    bot_system_message(user,'Не смог сформировать список бесед из ВК - попробуйте позже или обратитесь к разработчику :-(')
    bot_cancel_command(room,user)
    return False

def bot_system_message(user,message,notice=False):
  global log
  global lock
  global data
  try:
    log.debug("=start function=")
    log.info(message)
    bot_control_room=data["users"][user]["matrix_bot_data"]["control_room"]
    if notice:
      return send_notice(bot_control_room,message)
    else:
      return send_message(bot_control_room,message)
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute bot_system_message()")
    return False

def bot_cancel_command(room,user):
  global log
  global lock
  global data
  try:
    log.debug("=start function=")
    log.warning("=====  call bot fault  =====")
    bot_control_room=data["users"][user]["matrix_bot_data"]["control_room"]
    session_data_room=data["users"][user]["rooms"][room]
    data["users"][user]["rooms"][room]["state"]="listen_command"
    send_message(bot_control_room,'Отменил текущий режим (%s) и перешёл в начальный режим ожидания команд. Жду команд.'%session_data_room["state"])
    return True
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute bot_cancel_command()")
    bot_system_message(user,"внутренняя ошибка бота")
    return False

def debug_dump_json_to_file(filename, data):
  global log
  log.debug("=start function=")
  json_text=json.dumps(data, indent=4, sort_keys=True,ensure_ascii=False)
  f=open(filename,"w+")
  f.write(json_text)
  f.close()
  return True

def get_dialogs(vk_id):
  global log
  log.debug("=start function=")
  out={}
  # Формируем структуры:
  try:
    api = vk.API(get_session(vk_id), v=VK_API_VERSION)
    #dialogs = api.messages.getDialogs(count=200)
    dialogs = api.messages.getConversations(count=200,extended=1,fields="id,first_name,last_name,name,type")
    #debug_dump_json_to_file("dialogs_from_api.json",dialogs)
    out["groups"]={}
    if "groups" in dialogs:
      for item in dialogs["groups"]:
        out["groups"][item["id"]]=item
    log.debug("count groups=%d"%len(out["groups"]))

    out["users"]={}
    if "profiles" in dialogs:
      for item in dialogs["profiles"]:
        out["users"][item["id"]]=item
    log.debug("count users=%d"%len(out["users"]))

    out["chats"]={}
    if "items" in dialogs:
      # Чаты ( это не то же самое, что группы O_o):
      for item in dialogs["items"]:
        # приводим к единообразию:
        if item["conversation"]["peer"]["type"]=="chat":
          if item["conversation"]["chat_settings"]["state"]=="left" or item["conversation"]["chat_settings"]["state"]=="kicked":
            # пропуск покинутых диалогов:
            continue
          if "members_count" not in item["conversation"]["chat_settings"]:
            # пропуск пустых диалогов:
            continue
          elem={}
          elem["type"]="chat"
          elem["id"]=item["conversation"]["peer"]["id"]
          log.debug("type=%s, item=%s"%(elem["type"], elem["id"]))
          elem["users_count"]=item["conversation"]["chat_settings"]["members_count"]
          elem["title"]=item["conversation"]["chat_settings"]["title"]
          elem["state"]=item["conversation"]["chat_settings"]["state"]
          elem["title_ext"]=elem["title"]+" (групповой чат)"
          out["chats"][elem["id"]]=elem

        if item["conversation"]["peer"]["type"]=="group":
          elem={}
          elem["type"]="group"
          elem["id"]=item["conversation"]["peer"]["id"]
          elem["group_id"]=item["conversation"]["peer"]["local_id"]
          elem["title"]=out["groups"][elem["group_id"]]["name"]
          elem["title_ext"]=elem["title"]+" (сообщество)"
          out["chats"][elem["id"]]=elem

        if item["conversation"]["peer"]["type"]=="user":
          elem={}
          elem["type"]="user"
          elem["id"]=item["conversation"]["peer"]["id"]
          elem["user_id"]=item["conversation"]["peer"]["local_id"]
          elem["title"]=out["users"][elem["user_id"]]["first_name"]
          if out["users"][elem["user_id"]]["last_name"]!="":
            elem["title"]+=" "+out["users"][elem["user_id"]]["last_name"]
          elem["title_ext"]=elem["title"]
          out["chats"][elem["id"]]=elem
    log.debug("count chats=%d"%len(out["chats"]))

  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("get dialogs from VK API")
    log.debug("dialogs data was:")
    log.debug(json.dumps(dialogs, indent=4, sort_keys=True,ensure_ascii=False))
    return None
  #log.debug(json.dumps(out, indent=4, sort_keys=True,ensure_ascii=False))
  return out
  
def close_dialog(user,room_id):
  global log
  global client
  global lock
  global data
  try:
    log.debug("=start function=")
    log.debug("close_dialog()")
    log.debug("Try remove room: '%s' from data of user '%s'"%(room_id,user))
    if user in data["users"]:
      if "rooms" in data["users"][user]:
        if room_id in data["users"][user]["rooms"]:
          # удаляем запись об этой комнате из данных:
          log.info("Remove room: '%s' from data of user '%s'"%(room_id,user))
          del data["users"][user]["rooms"][room_id]
          log.info("save state data on disk")
          save_data(data)
          try:
            # Нужно выйти из комнаты:
            log.info("Leave from room: '%s'"%(room_id))
            response = client.api.leave_room(room_id)
          except Exception as e:
            log.error(get_exception_traceback_descr(e))
            log.error("error leave room: '%s'"%(room_id))
            return None
          try:
            # И забыть её:
            log.info("Forgot room: '%s'"%(room_id))
            response = client.api.forget_room(room_id)
          except Exception as e:
            log.error(get_exception_traceback_descr(e))
            log.error("error forgot room: '%s'"%(room_id))
            return None
          return None
          log.info("success close dialog for user invite user '%s' and room '%s'"%(user,room_id))
          return True
        else:
          log.warning("unknown room '%s' for user '%s'"%(room_id,user))
    else:
      log.warning("unknown user: '%s'"%(user))

    log.info("do not close dialog for user user '%s' and room '%s'"%(user,room_id))
    return False
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute close_dialog()")
    bot_system_message(user,"внутренняя ошибка бота при закрытии диалога")
    return False
              

def login_command(user,room,cmd):
  global log
  global lock
  global data
  try:
    log.debug("=start function=")
    log.debug("login_command()")
    session_data_vk=data["users"][user]["vk"]

    if conf.vk_app_id != None:
      # vk_app_id уже указан в конфиге:
      data["users"][user]["vk"]["vk_app_id"]=conf.vk_app_id

    # если не указан - спрашиваем у пользователя:
    if "vk_app_id" not in session_data_vk or session_data_vk["vk_app_id"]==None :
      send_message(room,'Пройдите по ссылке https://vk.com/editapp?act=create и создайте своё Standalone-приложение, затем во вкладке Настройки переведите Состояние в "Приложение включено" и "видно всем", не забудьте сохранить изменения!')
      send_message(room,'После этого скопируйте "ID приложения" в настройках у созданного перед этим приложения по ссылке https://vk.com/apps?act=manage  и пришлите мне сюда в чат. Я жду :-)')
      data["users"][user]["rooms"][room]["state"]="wait_vk_app_id"
    elif "vk_id" not in session_data_vk or session_data_vk["vk_id"]==None:
      send_message(room,'Нажмите по ссылке ниже. Откройте её и согласитесь. После скопируйте текст из адресной строки (именно адресной строки, а не из окна браузера) и отправьте эту ссылку мне сюда')
      link = 'https://oauth.vk.com/authorize?client_id={}&' \
             'display=page&redirect_uri=https://oauth.vk.com/blank.html&scope=friends,messages,offline,docs,photos,video' \
             '&response_type=token&v={}'.format(session_data_vk["vk_app_id"], VK_API_VERSION)
      send_message(room,link)
      data["users"][user]["rooms"][room]["state"]="wait_vk_id"
    else:
      send_message(room,'Вход уже выполнен!\n/logout для выхода.')
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute login_command()")
    bot_system_message(user,"внутренняя ошибка бота")
    return None




def replace_shields(text):
  global log
  log.debug("=start function=")
  text = text.replace('&lt;', '<')
  text = text.replace('&gt;', '>')
  text = text.replace('&amp;', '&')
  text = text.replace('&copy;', '©')
  text = text.replace('&reg;', '®')
  text = text.replace('&laquo;', '«')
  text = text.replace('&raquo;', '«')
  text = text.replace('&deg;', '°')
  text = text.replace('&trade;', '™')
  text = text.replace('&plusmn;', '±')
  return text

def save_data(data):
  global log
  log.debug("=start function=")
  log.debug("save to data_file:%s"%conf.data_file)
  try:
    #data_file=open(conf.data_file,"wb")
    data_file=open(conf.data_file,"w")
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("open(%s) for writing"%conf.data_file)
    return False
    
  try:
    data_file.write(json.dumps(data, indent=4, sort_keys=True,ensure_ascii=False))
    #pickle.dump(data,data_file)
    data_file.close()
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("json.dump to '%s'"%conf.data_file)
    print(json.dumps(data, indent=4, sort_keys=True,ensure_ascii=False))
    sys.exit(1)
    return False
  return True

def load_data():
  global log
  log.debug("=start function=")
  tmp_data_file=conf.data_file
  reset=False
  if os.path.exists(tmp_data_file):
    log.debug("Загружаем файл промежуточных данных: '%s'" % tmp_data_file)
    #data_file = open(tmp_data_file,'rb')
    data_file = open(tmp_data_file,'r')
    try:
      #data=pickle.load(data_file)
      data=json.loads(data_file.read())
      data_file.close()
      log.debug("Загрузили файл промежуточных данных: '%s'" % tmp_data_file)
      if not "users" in data:
        log.warning("Битый файл сессии - сброс")
        reset=True
      else:
        # успешно загрузили файл состояния - он в хорошем состоянии - сохраняем его как бэкап:
        try:
          backup_name=conf.data_file+'.backup'
          log.info("сохраняем успешно-загруженный файл как '%s'"%backup_name)
          f=open(backup_name,"w+")
          f.write(json.dumps(data, indent=4, sort_keys=True,ensure_ascii=False))
          f.close()
        except Exception as e:
          log.error(get_exception_traceback_descr(e))
          log.error("json.dump to '%s'"%conf.data_file)
          print(json.dumps(data, indent=4, sort_keys=True,ensure_ascii=False))
          sys.exit(1)
            
    except Exception as e:
      log.error(get_exception_traceback_descr(e))
      log.warning("Битый файл сессии - сброс")
      reset=True
  else:
    log.warning("Файл промежуточных данных не существует")
    reset=True
  if reset:
    try:
      log.info("сохраняем копию битого файла основных данных")
      backup_name=conf.data_file+'.failed.'+uuid.uuid4().hex
      log.warning("сохраняем битый файл как '%s'"%backup_name)
      f=open(conf.data_file,"r")
      backup_data=f.read()
      f.close()
      f=open(backup_name,"w+")
      f.write(backup_data)
      f.close()
      log.info("сохраняем бэкап последнего успешно-загруженного файла, чтобы его не перетёрло в случае сброса файла")
      backup_name=conf.data_file+'.backup'
      new_backup_name=conf.data_file+'.backup.'+uuid.uuid4().hex
      log.info("сохраняем прошлый бэкап файла данны как '%s'"%new_backup_name)
      f=open(backup_name,"r")
      backup_data=f.read()
      f.close()
      f=open(new_backup_name,"w+")
      f.write(backup_data)
      f.close()
    except Exception as e:
      log.error(get_exception_traceback_descr(e))
      log.warning("ошибка копирования битого файла данных в резервную копию или копирования прошлого бэкапа")
    if conf.try_recover_data_file_from_last_backup == True:
      log.info("пробуем загрузить последний успешный бэкап")
      try:
        backup_name=conf.data_file+'.backup'
        data_file = open(backup_name,'r')
        data=json.loads(data_file.read())
        data_file.close()
        if not "users" in data:
          log.warning("Битый файл сессии и в файле бэкапа :-( - сброс")
          reset=True
        else:
          log.debug("Загрузили файл промежуточных данных из последнего бэкапа: '%s'" % backup_name)
          reset=False
      except Exception as e:
        log.error(get_exception_traceback_descr(e))
        log.warning("Битый файл сессии и в файле бэкапа или бэкапа не существует :-( - сброс")
        reset=True
    if reset:
      log.warning("Сброс промежуточных данных")
      data={}
      data["users"]={}
    save_data(data)
  #debug_dump_json_to_file("debug_data_as_json.json",data)
  return data

def create_room(matrix_uid, room_name, avatar_data=None):
  global log
  global louser_id
  global client
  log.debug("=start function=")

  # сначала спрашиваем у сервера, есть ли такой пользователь (чтобы не создавать просто так комнату):
  try:
    response = client.api.get_display_name(matrix_uid)
  except MatrixRequestError as e:
    log.error("Couldn't get user display name - may be no such user on server? username = '%s'"%matrix_uid)
    log.error("skip create room for user '%s' - need admin!"%matrix_uid)
    return None
  log.debug("Success get display name '%s' for user '%s' - user exist. Try create room for this is user"%(response,matrix_uid))

  try:
    room=client.create_room(is_public=False, invitees=None)
  except MatrixRequestError as e:
    print(e)
    if e.code == 400:
      log.error("Room ID/Alias in the wrong format")
      return None
    else:
      log.error("Couldn't create room.")
      return None
  log.debug("New room created. room_id='%s'"%room.room_id)

  # выставляем имя комнаты:
  try:
    room.set_room_name(room_name)
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("error set_room_name room_id='%s' to '%s'"%(room.room_id, room_name))

  # выставляем аватар комнаты:
  if avatar_data!=None:
    log.debug("try set_matrix_room_avatar()")
    ret_value=set_matrix_room_avatar(room.room_id,avatar_data)
    log.debug("set_matrix_room_avatar() return:")
    log.debug(ret_value)
    if ret_value==None:
      log.error("set_matrix_room_avatar()")
    else:
      log.info("success set room avatar")

  # приглашаем пользователя в комнату:
  try:
    response = client.api.invite_user(room.room_id,matrix_uid)
  except MatrixRequestError as e:
    print(e)
    log.error("Can not invite user '%s' to room '%s'"%(matrix_uid,room.room_id))
    try:
      # Нужно выйти из комнаты:
      log.info("Leave from room: '%s'"%(room.room_id))
      response = client.api.leave_room(room.room_id)
    except Exception as e:
      log.error(get_exception_traceback_descr(e))
      log.error("error leave room: '%s'"%(room.room_id))
      return None
    try:
      # И забыть её:
      log.info("Forgot room: '%s'"%(room.room_id))
      response = client.api.forget_room(room.room_id)
    except Exception as e:
      log.error(get_exception_traceback_descr(e))
      log.error("error leave room: '%s'"%(room.room_id))
      return None
    return None
  log.debug("success invite user '%s' to room '%s'"%(matrix_uid,room.room_id))

  return room.room_id;

def send_html(room_id,html, useType=False):
  global client
  global log
  log.debug("=start function=")

  room=None
  try:
    room = client.join_room(room_id)
  except MatrixRequestError as e:
    print(e)
    if e.code == 400:
      log.error("Room ID/Alias in the wrong format")
      return False
    else:
      log.error("Couldn't find room.")
      return False
  try:
    event=room.send_html(html)
    if useType:
      log.debug(event)
      return event
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("Unknown error at send message '%s' to room '%s'"%(html,room_id))
    bot_system_message(user,'Не смог отправить сообщение в комнату: %s'%room_id)
    return False
  return True

def get_file(mxurl):
  global client
  global log
  log.debug("=start function=")
  log.debug("get_file 1")
  ret=None
  # получаем глобальную ссылку на файл:
  try:
    log.debug("get_file file 2")
    full_url=client.api.get_download_url(mxurl)
    log.debug("get_file file 3")
  except MatrixRequestError as e:
    log.error(e)
    if e.code == 400:
      log.error("ERROR download file")
      return None
    else:
      log.error("Couldn't download file (unknown error)")
      return None
  # скачиваем файл по ссылке:
  try:
    response = requests.get(full_url, stream=True)
    data = response.content      # a `bytes` object
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("fetch file data from url: %s"%full_url)
    return None
  return data

def send_message(room_id,message):
  global client
  global log
  log.debug("=start function=")

  #FIXME отладка парсера
  #print("message=%s"%message)
  #return True

  room=None
  try:
    room = client.join_room(room_id)
  except MatrixRequestError as e:
    print(e)
    if e.code == 400:
      log.error("Room ID/Alias in the wrong format")
      return False
    else:
      log.error("Couldn't find room.")
      return False
  try:
    room.send_text(message)
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("Unknown error at send message '%s' to room '%s'"%(message,room_id))
    return False
  return True

def send_notice(room_id,message):
  global client
  global log
  log.debug("=start function=")
  room=None
  try:
    room = client.join_room(room_id)
  except MatrixRequestError as e:
    print(e)
    if e.code == 400:
      log.error("Room ID/Alias in the wrong format")
      return False
    else:
      log.error("Couldn't find room.")
      return False
  try:
    room.send_notice(message)
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("Unknown error at send notice message '%s' to room '%s'"%(message,room_id))
    return False
  return True


# Called when a message is recieved.
def on_message(event):
  global client
  global log
  global lock
  try:
    log.debug("=start function=")
    formatted_body=None
    format_type=None
    reply_to_id=None
    file_url=None
    file_type=None

    log.debug("new MATRIX message:")
    #log.debug(json.dumps(event, indent=4, sort_keys=True,ensure_ascii=False))
    if event['type'] == "m.room.member":
        # join:
        if event['content']['membership'] == "join":
            log.info("{0} joined".format(event['content']['displayname']))
        # leave:
        elif event['content']['membership'] == "leave":
            log.info("{0} leave".format(event['sender']))
            # close room:
            log.debug("try lock() before access global data()")
            with lock:
              log.debug("success lock before process_command()")
              if close_dialog(event['sender'],event['room_id']) == False:
                log.warning("close_dialog()==False")
            log.debug("release lock() after access global data")
        return True
    elif event['type'] == "m.room.message":
        if event['content']['msgtype'] == "m.text":
            reply_to_id=None
            if "m.relates_to" in  event['content']:
              # это ответ на сообщение:
              reply_to_id=event['content']['m.relates_to']['m.in_reply_to']['event_id']
            formatted_body=None
            format_type=None
            if "formatted_body" in event['content'] and "format" in event['content']:
              formatted_body=event['content']['formatted_body']
              format_type=event['content']['format']

        elif event['content']['msgtype'] == "m.video":
          file_type=event['content']['info']['mimetype']
          file_url=event['content']['url']
        elif event['content']['msgtype'] == "m.image":
          file_url=event['content']['url']
          if "imageinfo" in event['content']['info']:
            file_type=event['content']['info']['imageinfo']['mimetype']
          else:
            file_type=event['content']['info']['mimetype']
        elif event['content']['msgtype'] == "m.file":
          file_url=event['content']['url']
          if "fileinfo" in event['content']['info']:
            file_type=event['content']['info']['fileinfo']['mimetype']
          else:
            file_type=event['content']['info']['mimetype']
        elif event['content']['msgtype'] == "m.audio":
          file_url=event['content']['url']
          if "fileinfo" in event['content']['info']:
            file_type=event['content']['info']['fileinfo']['mimetype']
          elif "audioinfo" in event['content']['info']:
            file_type=event['content']['info']['audioinfo']['mimetype']
          else:
            file_type=event['content']['info']['mimetype']

        log.debug("%s: %s"%(event['sender'], event['content']["body"]))
        log.debug("try lock before process_command()")
        with lock:
          log.debug("success lock before process_command()")
          if process_command(\
              event['sender'],\
              event['room_id'],\
              event['content']["body"],\
              formated_message=formatted_body,\
              format_type=format_type,\
              reply_to_id=reply_to_id,\
              file_url=file_url,\
              file_type=file_type\
            ) == False:
            log.error("error process command: '%s'"%event['content']["body"])
            return False
        log.debug("success lock() before access global data")
    else:
      log.warning("unknown type of event:")
      log.warning(event['type'])
      return False
    return True
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute on_message()")
    bot_system_message(user,"внутренняя ошибка бота")
    log.error("json of event:")
    log.error(json.dumps(event, indent=4, sort_keys=True,ensure_ascii=False))
    return False

def on_event(event):
  global log
  log.debug("=start function=")
  print("event:")
  print(event)
  #print(json.dumps(event, indent=4, sort_keys=True,ensure_ascii=False))

def on_invite(room, event):
  global client
  global log
  global lock
  global data
  log.debug("=start function=")

  if conf.debug:
    print("invite:")
    print("room_data:")
    print(room)
    print("event_data:")
    print(event)
    #print(json.dumps(event, indent=4, sort_keys=True,ensure_ascii=False))

  # Просматриваем сообщения:
  for event_item in event['events']:
    if event_item['type'] == "m.room.join_rules":
      if event_item['content']['join_rule'] == "invite":
        user=event_item["sender"]
        # проверка на разрешения:
        allow=False
        if len(conf.allow_domains)>0:
          for allow_domain in conf.allow_domains:
            if re.search('.*:%s$'%allow_domain.lower(), user.lower()) is not None:
              allow=True
              log.info("user: %s from allow domain: %s - allow invite"%(user, allow_domain))
              break
        if len(conf.allow_users)>0:
          for allow_user in conf.allow_users:
            if allow_user.lower() == user.lower():
              allow=True
              log.info("user: %s from allow users - allow invite"%user)
              break
        if len(conf.allow_domains)==0 and len(conf.allow_users)==0:
          allow=True

        if allow == True:
          # Приглашение вступить в комнату:
          room = client.join_room(room)
          room.send_text("Спасибо за приглашение! Недеюсь быть Вам полезным. :-)")
          room.send_text("Для справки по доступным командам - наберите: '!help' (или '!?', или '!h')")
          log.info("New user: '%s'"%user)
          # Прописываем системную группу для пользователя (группа, в которую будут сыпаться системные сообщения от бота и где он будет слушать команды):
          log.debug("try lock() before access global data()")
          with lock:
            log.debug("success lock() before access global data")
            if "users" not in data:
              data["users"]={}
            if user not in data["users"]:
              data["users"][user]={}
            if "matrix_bot_data" not in data["users"][user]:
              data["users"][user]["matrix_bot_data"]={}
            if "control_room" not in data["users"][user]["matrix_bot_data"]:
              data["users"][user]["matrix_bot_data"]["control_room"]=room.room_id
            save_data(data)
          log.debug("release lock() after access global data")

def exception_handler(e):
  global client
  global log
  log.debug("=start function=")
  log.error("main MATRIX listener thread except. He must retrying...")
  print(e)
  log.info("wait 30 second before retrying...")
  time.sleep(30)

def main():
  global client
  global data
  global log
  global lock

  lock = threading.RLock()

  log.debug("try lock() before access global data()")
  with lock:
    log.debug("success lock() before access global data")
    data=load_data()
  log.debug("release lock() after access global data")

  log.info("try init matrix-client")
  client = MatrixClient(conf.server)
  log.info("success init matrix-client")

  while True:
    try:
        log.info("try login matrix-client")
        token = client.login(username=conf.username, password=conf.password,device_id=conf.device_id)
        log.info("success login matrix-client")
    except MatrixRequestError as e:
      print(e)
      log.debug(e)
      if e.code == 403:
        log.error("Bad username or password.")
      else:
        log.error("Check your sever details are correct.")
      sys.exit(4)
    except MissingSchema as e:
      print(e)
      log.error("Bad URL format.")
      log.error(get_exception_traceback_descr(e))
      log.debug(e)
      sys.exit(4)
    except Exception as e:
      log.error("Unknown connect error")
      log.error(get_exception_traceback_descr(e))
      log.debug(e)
      log.info("sleep 30 second and try again...")
      time.sleep(30)
      continue
    break

  try:
    log.info("try init listeners")
    client.add_listener(on_message)
    client.add_ephemeral_listener(on_event)
    client.add_invite_listener(on_invite)
    client.start_listener_thread(exception_handler=exception_handler)
    log.info("success init listeners")
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute main() at init listeners")
    sys.exit(1)

  try:
    x=0
    log.info("enter main loop")
    while True:
      log.debug("step %d"%x)
      # Запускаем незапущенные потоки - при старте бота или же если подключился новый пользователь:
      num=start_vk_polls(x)
      if num > 0:
        log.info("start_vk_polls() start %d new poller proccess for receive VK messages"%num)
      time.sleep(10)
      check_bot_status()
      x+=1
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute main() at main loop")
    sys.exit(1)

  log.info("exit main loop")

def check_bot_status():
  global client
  global data
  global log
  global lock
  try:
    log.debug("=start function=")
    
    change_flag=False
    cur_ts = int(time.time())

    for user in data["users"]:
      user_data=data["users"][user]

      # vk connection status:
      if "vk" in user_data:
        prev_connection_status="unknown"
        if "connection_status" in data["users"][user]["vk"]:
          prev_connection_status=data["users"][user]["vk"]["connection_status"]
        if "ts_check_poll" in user_data["vk"]:
          ts_check_poll=0
          log.debug("try lock() before access global data()")
          with lock:
            log.debug("success lock() before access global data")
            ts_check_poll=user_data["vk"]["ts_check_poll"] 
          log.debug("release lock() after access global data")
          delta=cur_ts-ts_check_poll
          log.debug("delta=%d"%delta)
          if delta > 600:
            log.debug("try lock() before access global data()")
            with lock:
              log.debug("success lock() before access global data")
              data["users"][user]["vk"]["connection_status"]="error"
              data["users"][user]["vk"]["connection_status_descr"]="более 10 минут не обновлялись данные из VK - пробую переподключиться"
              data["users"][user]["vk"]["connection_status_update_ts"]=cur_ts
            log.debug("release lock() after access global data")
            log.info("wait 240 sec before set exif_flag=1")
            # Задача на переподключение:
            time.sleep(240) # ждём на всякий случай:
            log.info("again check connection before before set exif_flag=1")
            # Заново проверяем статус - если ситуация не изменилась - то выставим статус на переподключение:
            cur_ts = int(time.time())
            log.debug("try lock() before access global data()")
            with lock:
              log.debug("success lock() before access global data")
              ts_check_poll=user_data["vk"]["ts_check_poll"] 
            log.debug("release lock() after access global data")
            delta=cur_ts-ts_check_poll
            if delta > 600:
              log.info("delta not connection = %d seconds. Set exit_flag = 1" % delta)
              log.debug("try lock() before access global data()")
              with lock:
                log.debug("success lock() before access global data")
                if "exit" in data["users"][user]["vk"]:
                  log.debug("old status exit_flag for user %s = %s"%(user,str(data["users"][user]["vk"]["exit"])))
                log.debug("set exit_flag for user '%s' to True"%user)
                data["users"][user]["vk"]["exit"]=True
              log.debug("release lock() after access global data")
            else:
              data["users"][user]["vk"]["exit"]=False
              log.info("at 240 timeout bot was recconnect success - then we do not set exit_flag. Exit check_bot_status()")
          else:
            log.debug("try lock() before access global data()")
            with lock:
              log.debug("success lock() before access global data")
              data["users"][user]["vk"]["connection_status"]="success"
              data["users"][user]["vk"]["connection_status_descr"]="нет ошибок"
              data["users"][user]["vk"]["connection_status_update_ts"]=cur_ts
            log.debug("release lock() after access global data")
        if "connection_status" in data["users"][user]["vk"]:
          if prev_connection_status!=data["users"][user]["vk"]["connection_status"]:
            change_flag=True
            bot_system_message(user,"Изменён статус соединения с VK на '%s', детальное описание: '%s'"%(\
              data["users"][user]["vk"]["connection_status"],\
              data["users"][user]["vk"]["connection_status_descr"]\
            ))
    return change_flag
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute check_bot_status()")
    return False

def check_thread_exist(vk_id):
  global log
  try:
    log.debug("=start function=")
    for th in threading.enumerate():
        if th.getName() == 'vk' + str(vk_id):
            return True
    return False
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute check_thread_exist()")
    return False

def stop_thread(vk_id):
  global log
  try:
    log.debug("=start function=")
    for th in threading.enumerate():
        if th.getName() == 'vk' + str(vk_id):
          #th._stop_event.set()
          #return True
          # FIXME
          log.info("FIXME pass hard stop thread - skip ")
    return False
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute stop_thread()")
    return False

# запуск потоков получения сообщений:
def start_vk_polls(check_iteration):
  global data
  global lock
  global log
  try:
    log.debug("=start function=")
    started=0
    for user in data["users"]:
      if "vk" in data["users"][user] and "vk_id" in data["users"][user]["vk"]:
        log.debug("try lock() before access global data()")
        with lock:
          log.debug("success lock() before access global data")
          vk_data=data["users"][user]["vk"]
          vk_id=data["users"][user]["vk"]["vk_id"]
          exit_flag=data["users"][user]["vk"]["exit"]
        log.debug("release lock() after access global data")
        if exit_flag:
          log.info("exit_flag=True, try stop thread for user %s"%user)
          time.sleep(3)
          if stop_thread(vk_id) == False:
            log.error("stop_thread(vk_id)")
          else:
            log.debug("success stop thread, try set exit_flag to False")
            with lock:
              log.debug("success lock() before access global data")
              log.debug("set exit_flag for user '%s' to False"%user)
              data["users"][user]["vk"]["exit"]=False
            log.debug("release lock() after access global data")
            log.debug("wait before restart thhread")
            time.sleep(5)
        if check_thread_exist(vk_id) == False:
          log.info("no thread for user '%s' with name: '%s' - try start new tread"%(user,"vk"+str(vk_id)))
          if check_iteration > 0:
            # при первом запуске (и перезапуске сервиса) моста не сообщаем пользователям о запуске их потоков:
            bot_system_message(user,"Не обнаружил потока, слушающего сообщения для пользователя '%s' и его VK id='%s'"%(user,str(vk_id)))
          # обновляем информацию о пользователе:
          if update_user_info(user) == False:
            log.error("update_user_info")
          if check_iteration > 0:
            # при первом запуске (и перезапуске сервиса) моста не сообщаем пользователям о запуске их потоков:
            bot_system_message(user,"Запускаю процесс получения сообщений из ВК...")
          t = threading.Thread(name='vk' + str(vk_id), target=vk_receiver_thread, args=(user,))
          t.setDaemon(True)
          t.start()
          started+=1
          if check_iteration > 0:
            # при первом запуске (и перезапуске сервиса) моста не сообщаем пользователям о запуске их потоков:
            bot_system_message(user,"Успешно запустил процесс получения сообщений из ВК.")
    return started
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute start_vk_polls()")
    data["users"][user]["vk"]["exit"] = True
    return 0

def get_name_from_url(url):
  global log
  try:
    log.debug("=start function=")
    return re.sub('.*/', '', url)
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute get_name_from_url()")
    return None

def send_file_to_matrix(room,sender_name,attachment):
  global log
  log.debug("=start function=")
  try:
    src=attachment["doc"]['url']
    size=attachment["doc"]['size']
    
    image_data=get_data_from_url(src)
    if image_data==None:
      log.error("get image from url: %s"%src)
      return False

    # определение типа:
    ext=attachment["doc"]["ext"]
    mimetype="text/plain"
    if ext == "txt":
      mimetype="text/plain"
    elif ext == "doc": 
      mimetype="application/msword"
    elif ext == "xls": 
      mimetype="application/vnd.ms-excel"
    elif ext == "odt": 
      mimetype="application/vnd.oasis.opendocument.text"
    elif ext == "ods": 
      mimetype="application/vnd.oasis.opendocument.spreadsheet"
      
    mxc_url=upload_file(image_data,mimetype)
    if mxc_url == None:
      log.error("uload file to matrix server")
      return False
    log.debug("send file 1")
    if "title" in attachment["doc"]:
      file_name=attachment["doc"]["title"]
    else:
      file_name=get_name_from_url(src)

    if sender_name!=None:
      file_name=sender_name+' прислал файл: '+file_name

    if matrix_send_file(room,mxc_url,file_name,mimetype,size) == False:
      log.error("send file to room")
      return False
  except Exception as e:
    log.error("exception at parse attachemt '%s': %s"%(attachment["type"],e))
    log.error("json of attachment:")
    log.error(json.dumps(attachment, indent=4, sort_keys=True,ensure_ascii=False))
    return False
  return True

def create_reply_forward_text_for_matrix(user,fwd):
  global log
  global data
  try:
    fwd_uid=fwd["from_id"]
    fwd_text=fwd["text"]
    user_profile=get_user_profile_by_uid(user,fwd_uid)
    fwd_user_name=fwd_uid
    if user_profile!=None:
      fwd_user_name=user_profile["first_name"] + " " + user_profile["last_name"]
    text="<blockquote>\n<p>В ответ на реплику от <strong>%(fwd_user)s</strong>:</p><p>%(fwd_text)s</p>\n" % {"fwd_user":fwd_user_name, "fwd_text":fwd_text}
    # если это ответ на вложения, то добавляем их как ссылки:
    descr="вложение"
    if "attachments" in fwd:
      for attachment in fwd["attachments"]:
        url=None
        if attachment['type']=="photo":
          descr="фото"
          photo_data=get_photo_url_from_photo_attachment(attachment)
          if photo_data!=None:
            url=photo_data["url"]
        elif attachment['type']=="video":
          descr="видео"
          url="https://vk.com/video%(owner_id)s_%(vid)s"%{"owner_id":attachment["video"]["owner_id"],"vid":attachment["video"]["id"]}
        elif attachment['type']=="audio_message":
          descr="голосовое сообщение"
          url=attachment["audio_message"]['link_ogg']
        elif attachment['type']=="audio":
          descr="аудио-файл"
          url=attachment["audio"]['url']
        elif attachment['type']=="doc":
          descr="документ"
          url=attachment["doc"]['url']
        if url!=None:
          text+="<p>%(descr)s: %(url)s</p>\n" % {"url":url,"descr":descr}
    if "geo" in fwd:
      geo=fwd["geo"]
      if geo["type"]=='point':
        coordinates=geo["coordinates"]
        lat=coordinates["latitude"]
        lon=coordinates["longitude"]
        place_name=geo["place"]["title"]
        geo_url="https://opentopomap.org/#marker=13/%(lat)s/%(lon)s"%{"lat":lat,"lon":lon}
        text+="<p>местоположение: %(geo_url)s (%(place_name)s)</p>\n" % {"geo_url":geo_url,"place_name":place_name}
      else:
        text+="<p>неизвестный тип местоположения</p>\n"
    text+="</blockquote>\n"
    return text
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute create_reply_forward_text_for_matrix()")
    bot_system_message(user,"внутренняя ошибка бота")
    return None


def send_geo_to_matrix(room,sender_name,geo):
  global log
  log.debug("=start function=")
  try:
    if geo["type"]=='point':
      coordinates=geo["coordinates"]
      lat=coordinates["latitude"]
      lon=coordinates["longitude"]
      place_name=geo["place"]["title"]
      
      geo_url="https://opentopomap.org/#marker=13/%(lat)s/%(lon)s"%{"lat":lat,"lon":lon}

      if sender_name!=None:
        text = sender_name + ' прислал местоположение (%s, %s):\n'%(lat,lon) + geo_url
      else:
        text = 'местоположение (%s, %s):\n'%(lat,lon) + geo_url
      send_message(room,text)
      return True
      
      # TODO добавить превью карты (на данный момент этот сайт не работает):
      preview_src="https://staticmap.openstreetmap.de/staticmap.php?center=%(lat)f,%(lon)f&zoom=14&size=400x300&maptype=mapnik"%{"lat":lat,"lon":lon}
      log.debug("try get static map preview from url: %s"%preview_src)
      image_data=get_data_from_url(preview_src,referer="osm.org")
      if image_data==None:
        log.error("get image from url: %s"%src)
        return False

      # TODO добавить определение типа:
      mimetype="image/png"
      size=len(image_data)
        
      mxc_url=upload_file(image_data,mimetype)
      if mxc_url == None:
        log.error("uload file to matrix server")
        return False
      log.debug("send file 1")
      file_name=place_name+".png"

      size=len(image_data)
      if matrix_send_image(room,mxc_url,file_name,mimetype,size=size) == False:
        log.error("send file to room")
        return False
    else:
      bot_system_message(user,"получен неизвестный тип гео-данных - прпоускаю")
      send_message(room,"получен неизвестный тип гео-данных - прпоускаю")
      return False
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute send_geo_to_matrix()")
    return False


def send_stiker_to_matrix(room,sender_name,attachment):
  global log
  try:
    log.debug("=start function=")
    image_data=get_image_url_from_stiker_attachment(attachment)
    if image_data == None:
      log.error("get src for photo")
      log.error(attachment["photo"])
      return False
    src=image_data["url"]
    height=image_data["height"]
    width=image_data["width"]

    log.debug("url=%s"%src)
    
    image_data=get_data_from_url(src)
    if image_data==None:
      log.error("get image from url: %s"%src)
      return False

    # TODO добавить определение типа:
    mimetype="image/png"
    size=len(image_data)
      
    mxc_url=upload_file(image_data,mimetype)
    if mxc_url == None:
      log.error("uload file to matrix server")
      return False
    log.debug("send file 1")
    if "sticker_id" in attachment["sticker"]:
      file_name=str(attachment["sticker"]["sticker_id"])
    else:
      file_name=get_name_from_url(src)

    file_name=file_name+".png"

    if sender_name!=None:
      file_name=sender_name+' прислал стикер: '+file_name

    log.debug("file_name=%s"%file_name)

    if matrix_send_image(room,mxc_url,file_name,mimetype,height,width,size) == False:
      log.error("send file to room")
      return False
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at parse attachemt '%s': %s"%(attachment["type"],e))
    log.error("json of attachment:")
    log.error(json.dumps(attachment, indent=4, sort_keys=True,ensure_ascii=False))
    return False
  return True

def send_photo_to_matrix(room,sender_name,attachment):
  global log
  try:
    log.debug("=start function=")
    photo_data=get_photo_url_from_photo_attachment(attachment)
    if photo_data == None:
      log.error("get src for photo")
      log.error(attachment["photo"])
      return False
    src=photo_data["url"]
    height=photo_data["height"]
    width=photo_data["width"]
    
    image_data=get_data_from_url(src)
    if image_data==None:
      log.error("get image from url: %s"%src)
      return False

    # TODO добавить определение типа:
    mimetype="image/jpeg"
    size=len(image_data)
      
    mxc_url=upload_file(image_data,mimetype)
    if mxc_url == None:
      log.error("uload file to matrix server")
      return False
    log.debug("send file 1")
    if "title" in attachment["photo"]:
      file_name=attachment["photo"]["title"]
    else:
      file_name=get_name_from_url(src)

    if sender_name!=None:
      file_name=sender_name+' прислал изображение: '+file_name

    if matrix_send_image(room,mxc_url,file_name,mimetype,height,width,size) == False:
      log.error("send file to room")
      return False
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at parse attachemt '%s': %s"%(attachment["type"],e))
    log.error("json of attachment:")
    log.error(json.dumps(attachment, indent=4, sort_keys=True,ensure_ascii=False))
    return False
  return True

attachmentHuman = {
  "doc":"Документ",
  "audio":"Аудио",
  "photo":"Фотография",
  "audio_message":"Голосове сообщение",
  "video":"Видео"
}

def send_wall_to_matrix(room,sender_name,attachment):
  global log
  try:
    log.debug("=start function=")
    text=""
    if sender_name!=None:
      text+="<p><strong>%(sender_name)s</strong>:</p>\n"%{"sender_name":sender_name}
    text+="<blockquote>\n<p><a href='https://vk.com/wall%(from_id)s_%(post_id)s'>Запись на стене</a>:</p>\n<p>%(wall_text)s</p>\n" % {"from_id":attachment["wall"]["from_id"],"post_id":attachment["wall"]["id"],"wall_text":attachment["wall"]["text"]}
    # если на стене были вложения, то добавляем их как ссылки:
    if "attachments" in attachment["wall"]:
      for attachment in attachment["wall"]["attachments"]:
        url=None
        if attachment['type']=="photo":
          data_item=get_photo_url_from_photo_attachment(attachment)
          if data_item!=None:
            url=data_item["url"]
          else:
            url=None
            bot_system_message(user,"при разборе вложений 'photo' в сообщении со стены - произошли ошибки")
        elif attachment['type']=="video":
          url="https://vk.com/video%(owner_id)s_%(vid)s"%{"owner_id":attachment["video"]["owner_id"],"vid":attachment["video"]["id"]}
        elif attachment['type']=="audio":
          url=attachment["audio"]['url']
        elif attachment['type']=="audio_message":
          url=attachment["audio_message"]['link_ogg']
        elif attachment['type']=="doc":
          url=attachment["doc"]['url']
        if url!=None:
          text+="<p><a href='%(url)s'>%(type)s</a> </p>\n" % {"url":url, "type":attachmentHuman[attachment['type']]}
    text+="</blockquote>\n"
    if send_html(room,text)==False:
      log.error("send_html()")
      return False
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at parse attachemt wall()")
    log.error("json of attachment:")
    log.error(json.dumps(attachment, indent=4, sort_keys=True,ensure_ascii=False))
    return False
  return True

def send_link_to_matrix(room,sender_name,attachment):
  global log
  try:
    log.debug("=start function=")
    text=""
    if sender_name!=None:
      text+="<p><strong>%(sender_name)s</strong>:</p>\n"%{"sender_name":sender_name}
    text+="<blockquote>\n<p>Пересланная ссылка:</p>\n<p>%(title)s</p>\n" % {"title":attachment["link"]["title"]}
    text+=attachment["link"]["url"]
    text+="\n"
    if "photo" in attachment["link"]:
      data_item=get_photo_url_from_photo_attachment(attachment["link"])
      if data_item!=None:
        photo_url=data_item["url"]
      else:
        photo_url=None
        bot_system_message(user,"при разборе вложений 'photo' во вложении 'link' - произошли ошибки")
      if photo_url!=None:
        text+="<p>вложение: %(url)s</p>\n" % {"url":photo_url}
    text+="</blockquote>\n"
    if send_html(room,text)==False:
      log.error("send_html()")
      bot_system_message(user,"Не смог отправить сообщение в комнату: '%s', сообщение было: %s"%(room,text))
      return False
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at parse attachemt '%s': %s"%(attachment["type"],e))
    log.error("json of attachment:")
    log.error(json.dumps(attachment, indent=4, sort_keys=True,ensure_ascii=False))
    return False
  return True

def send_video_to_matrix(room,sender_name,attachment):
  global log
  ret=False
  try:
    log.debug("=start function=")
    src=None
    if 'first_frame_320' in attachment["video"]:
      src=attachment["video"]['first_frame_320']
    elif 'photo_320' in attachment["video"]:
      src=attachment["video"]['photo_320']

    description=None
    if 'description' in attachment["video"]:
      description=attachment["video"]["description"]
    
    image_data=get_data_from_url(src)
    if image_data==None:
      log.error("get image from url: %s"%src)
      return False

    # TODO добавить определение типа:
    mimetype="image/jpeg"
    size=len(image_data)
      
    mxc_url=upload_file(image_data,mimetype)
    if mxc_url == None:
      log.error("uload file to matrix server")
      return False
    log.debug("send file 1")
    if "title" in attachment["video"]:
      file_name=attachment["video"]["title"]+"(превью видео).jpg"
    else:
      file_name=get_name_from_url(src)

    if sender_name!=None:
      file_name=sender_name+' прислал изображение: '+file_name

    if matrix_send_image(room,mxc_url,file_name,mimetype=mimetype,height=0,width=0,size=size) == False:
      log.error("send file to room")
      return False
    video_url="https://vk.com/video%(owner_id)s_%(vid)s"%{"owner_id":attachment["video"]["owner_id"],"vid":attachment["video"]["id"]}
    message="Ссылка на просмотр потокового видео: %s"%video_url
    if description!=None:
      message+="\nОписание: %s"%description
    ret=send_message(room,message)
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at parse attachemt '%s': %s"%(attachment["type"],e))
    log.error("json of attachment:")
    log.error(json.dumps(attachment, indent=4, sort_keys=True,ensure_ascii=False))
    return False
  return ret

def get_exception_traceback_descr(e):
  tb_str = traceback.format_exception(etype=type(e), value=e, tb=e.__traceback__)
  result=""
  for msg in tb_str:
    result+=msg
  return result

def send_audio_to_matrix(room,sender_name,attachment):
  global log
  try:
    log.debug("=start function=")
    src=attachment["audio"]['url']
    size=0
    duration=attachment["audio"]["duration"]
    file_name=attachment["audio"]["title"]+" ("+attachment["audio"]["title"]+").mp3"
    # TODO добавить определение типа:
    mimetype="audio/mpeg"
    
    audio_data=get_data_from_url(src)
    if audio_data==None:
      log.error("get image from url: %s"%src)
      return False
      
    mxc_url=upload_file(audio_data,mimetype)
    if mxc_url == None:
      log.error("uload file to matrix server")
      return False
    log.debug("send file 1")

    if sender_name!=None:
      file_name=sender_name+' прислал песню: '+file_name

    if matrix_send_audio(room,mxc_url,file_name,mimetype,size,duration) == False:
      log.error("send file to room")
      return False
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at parse attachemt '%s': %s"%(attachment["type"],e))
    log.error("json of attachment:")
    log.error(json.dumps(attachment, indent=4, sort_keys=True,ensure_ascii=False))
    return False
  return True

def send_voice_to_matrix(room,sender_name,attachment):
  global log
  try:
    log.debug("=start function=")
    src=attachment["audio_message"]['link_ogg']
    duration=attachment["audio_message"]['duration']
    file_name="голосовое_сообщение.ogg"
    mimetype="audio/ogg"
    
    audio_data=get_data_from_url(src)
    if audio_data==None:
      log.error("get voice from url: %s"%src)
      return False
    size=len(audio_data)
      
    mxc_url=upload_file(audio_data,mimetype)
    if mxc_url == None:
      log.error("uload file to matrix server")
      return False
    log.debug("send file 1")

    if sender_name!=None:
      file_name=sender_name+' прислал голосовое сообщение: '+file_name

    if matrix_send_audio(room,mxc_url,file_name,mimetype,size=size,duration=duration) == False:
      log.error("send file to room")
      return False
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at parse attachemt '%s': %s"%(attachment["type"],e))
    log.error("json of attachment:")
    log.error(json.dumps(attachment, indent=4, sort_keys=True,ensure_ascii=False))
    return False
  return True

def send_notice_about_attachments(user,room,sender_name,attachments):
  global log
  try:
    log.debug("=start function=")
    success_status=True
    for attachment in attachments:
      # Отправляем фото:
      if attachment["type"]=="photo":
        text="Вы отправили фото из другой клиентской программы"
        if send_notice(room,text) == False:
          log.error("send_notice(%s)"%text)
          success_status=False
      # Отправляем звуковой файл:
      elif attachment["type"]=="audio":
        text="Вы отправили аудио-файл из другой клиентской программы"
        if send_notice(room,text) == False:
          log.error("send_notice(%s)"%text)
          success_status=False
      # Отправляем звуковое сообщение:
      elif attachment["type"]=="audio_message":
        text="Вы отправили голосовое сообщение из другой клиентской программы"
        if send_notice(room,text) == False:
          log.error("send_notice(%s)"%text)
          success_status=False
      # Отправляем видео:
      elif attachment["type"]=="video":
        text="Вы отправили видео-файл из другой клиентской программы"
        if send_notice(room,text) == False:
          log.error("send_notice(%s)"%text)
          success_status=False
      # документы:
      elif attachment["type"]=="doc":
        text="Вы отправили файл из другой клиентской программы"
        if send_notice(room,text) == False:
          log.error("send_notice(%s)"%text)
          success_status=False
      # сообщение со стены:
      elif attachment["type"]=="wall":
        text="Вы отправили сообщение со стены из другой клиентской программы"
        if send_notice(room,text) == False:
          log.error("send_notice(%s)"%text)
          success_status=False
      else:
        text="Вы отправили неподдерживаемый тип сообщения (%s) из другой клиентской программы"%attachment["type"]
        if send_notice(room,text) == False:
          log.error("send_notice(%s)"%text)
          success_status=False
    return success_status
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute send_notice_about_attachments()")
    bot_system_message(user,"внутренняя ошибка бота")
    return False

def send_attachments(user,room,sender_name,attachments):
  global log
  try:
    log.debug("=start function=")
    success_status=True
    for attachment in attachments:
      # Отправляем фото:
      if attachment["type"]=="photo":
        if send_photo_to_matrix(room,sender_name,attachment)==False:
          log.error("send_photo_to_matrix()")
          bot_system_message(user,"при разборе вложений с типом '%s' - произошли ошибки"%attachment["type"])
          success_status=False
      elif attachment["type"]=="sticker":
        if send_stiker_to_matrix(room,sender_name,attachment)==False:
          log.error("send_photo_to_matrix()")
          bot_system_message(user,"при разборе вложений с типом '%s' - произошли ошибки"%attachment["type"])
          success_status=False
      # Отправляем звуковой файл:
      elif attachment["type"]=="audio":
        if send_audio_to_matrix(room,sender_name,attachment)==False:
          log.error("send_audio_to_matrix()")
          bot_system_message(user,"при разборе вложений с типом '%s' - произошли ошибки"%attachment["type"])
          success_status=False
      # Отправляем звуковое сообщение:
      elif attachment["type"]=="audio_message":
        if send_voice_to_matrix(room,sender_name,attachment)==False:
          log.error("send_voice_to_matrix()")
          bot_system_message(user,"при разборе вложений с типом '%s' - произошли ошибки"%attachment["type"])
          success_status=False
      # Отправляем видео:
      elif attachment["type"]=="video":
        if send_video_to_matrix(room,sender_name,attachment)==False:
          log.error("send_video_to_matrix()")
          bot_system_message(user,"при разборе вложений с типом '%s' - произошли ошибки"%attachment["type"])
          success_status=False
      # документы:
      elif attachment["type"]=="doc":
        # иные прикреплённые документы:
        if send_file_to_matrix(room,sender_name,attachment)==False:
          log.error("send_file_to_matrix()")
          bot_system_message(user,"при разборе вложений с типом '%s' - произошли ошибки"%attachment["type"])
          success_status=False
      # сообщение со стены:
      elif attachment["type"]=="wall":
        if send_wall_to_matrix(room,sender_name,attachment)==False:
          log.error("send_wall_to_matrix()")
          bot_system_message(user,"при разборе вложений с типом '%s' - произошли ошибки"%attachment["type"])
          success_status=False
      # ссылка:
      elif attachment["type"]=="link":
        if send_link_to_matrix(room,sender_name,attachment)==False:
          log.error("send_link_to_matrix()")
          bot_system_message(user,"при разборе вложений с типом '%s' - произошли ошибки"%attachment["type"])
          success_status=False
      else:
        log.error("unknown attachment type - skip. attachment type=%s"%attachment["type"])
        bot_system_message(user,"Из ВК пришёл неизвестный тип вложения (%s) для комнаты '%s'"%(attachment["type"],get_name_of_matrix_room(room)))
        send_message(room,"Из ВК пришёл неизвестный тип вложения (%s)"%attachment["type"])
    return success_status
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception in send_attachments()")
    bot_system_message(user,"при разборе вложений произошли ошибки. Сообщение не принято. Обратитесь к разработчику, проверьте сообщения в ВК")
    log.error("json of attachments:")
    log.error(json.dumps(attachment, indent=4, sort_keys=True,ensure_ascii=False))
    return False

def get_data_from_url(url,referer=None):
  global log
  log.debug("=start function=")
  try:
    if referer!=None:
      response = requests.get(url, stream=True,headers=dict(referer = referer))
    else:
      response = requests.get(url, stream=True)
    data = response.content      # a `bytes` object
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("fetch data from url: %s"%url)
    return None
  return data


def matrix_send_audio(room_id,url,name,mimetype="audio/mpeg",size=0,duration=0):
  global log
  global client
  log.debug("=start function=")
  ret=None
  room=None
  try:
    room = client.join_room(room_id)
  except MatrixRequestError as e:
    print(e)
    if e.code == 400:
      log.error("Room ID/Alias in the wrong format")
      return False
    else:
      log.error("Couldn't find room.")
      return False
  audioinfo={}
  audioinfo["mimetype"]=mimetype
  audioinfo["size"]=size
  audioinfo["duration"]=duration
  try:
    log.debug("send file 2")
    #ret=room.send_image(url,name,imageinfo)
    ret=room.send_audio(url,name,audioinfo=audioinfo)
    log.debug("send file 3")
  except MatrixRequestError as e:
    print(e)
    if e.code == 400:
      log.error("ERROR send audio with mxurl=%s"%url)
      return False
    else:
      log.error("Couldn't send audio (unknown error) with mxurl=%s"%url)
      return False
  return True

def matrix_send_image(room_id,url,name,mimetype,height=None,width=None,size=None):
  global log
  global client
  log.debug("=start function=")
  ret=None
  room=None
  try:
    room = client.join_room(room_id)
  except MatrixRequestError as e:
    print(e)
    if e.code == 400:
      log.error("Room ID/Alias in the wrong format")
      return False
    else:
      log.error("Couldn't find room.")
      return False
  imageinfo={}
  imageinfo["mimetype"]=mimetype
  if size!=None:
    imageinfo["size"]=size
  if height!=None:
    imageinfo["h"]=height
  if width!=None:
    imageinfo["w"]=width
  try:
    log.debug("send file 2")
    ret=room.send_image(url,name,imageinfo=imageinfo)
    #ret=room.send_image(url,name)
    log.debug("send file 3")
  except MatrixRequestError as e:
    log.error(e)
    if e.code == 400:
      log.error("ERROR 400 send image with mxurl=%s"%url)
      return False
    else:
      log.error("Couldn't send image (unknown error) with mxurl=%s"%url)
      return False
  return True

def matrix_send_file(room_id,url,name,mimetype,size):
  global log
  global client
  log.debug("=start function=")
  ret=None
  room=None
  try:
    room = client.join_room(room_id)
  except MatrixRequestError as e:
    print(e)
    if e.code == 400:
      log.error("Room ID/Alias in the wrong format")
      return False
    else:
      log.error("Couldn't find room.")
      return False
  fileinfo={}
  fileinfo["mimetype"]=mimetype
  fileinfo["size"]=size
  try:
    log.debug("send file 2")
    ret=room.send_file(url,name,fileinfo=fileinfo)
    log.debug("send file 3")
  except MatrixRequestError as e:
    print(e)
    if e.code == 400:
      log.error("ERROR send file with mxurl=%s"%url)
      return False
    else:
      log.error("Couldn't send file (unknown error) with mxurl=%s"%url)
      return False
  return True

def upload_file(content,content_type,filename=None):
  global log
  global client
  log.debug("=start function=")
  log.debug("upload file 1")
  ret=None
  try:
    log.debug("size of data = %d"%len(content))
    log.debug("upload file 2")
    ret=client.upload(content,content_type)
    log.debug("upload file 3")
  except MatrixRequestError as e:
    print(e)
    if e.code == 400:
      log.error("ERROR upload file")
      return None
    else:
      log.error("Couldn't upload file (unknown error)")
      return None
  return ret

def check_equal_messages(vk_body,matrix_body):
  global log
  try:
    log.debug("=start function=")
    log.debug("check_equal_messages(%s,%s)"%(vk_body,matrix_body))
    if vk_body==matrix_body:
      return True
    # заменяем разные символы:
    src=vk_body.replace('&gt;','>')\
          .replace('&lt;','<')\
          .replace('<br>','\n')
    log.debug("check_equal_messages() after replace: vk_body: %s"%src)
    log.debug("check_equal_messages() after replace: matrix_body: %s"%matrix_body)
    if src==matrix_body:
      log.debug("check_equal_messages() equal!")
      return True
    else:
      log.debug("check_equal_messages() NOT equal!")
    return False
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute check_equal_messages()")
    return False

def get_user_profile_by_uid(user,uid):
  global log
  global data
  try:
    log.debug("=start function=")
    dialogs=get_dialogs(data["users"][user]["vk"]["vk_id"])
    if dialogs == None:
      log.error("get_dialogs() for user=%s"%user)
      bot_system_message(user,"внутренняя ошибка бота при получении списка диалогов пользователя в функции get_user_profile_by_uid()")
      return None
      
    if uid in dialogs["users"]:
      return dialogs["users"][uid]
    else:
      return None
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute get_user_profile_by_uid()")
    bot_system_message(user,"внутренняя ошибка бота")
    return None

def get_image_url_from_stiker_attachment(attachment):
  global log
  try:
    log.debug("=start function=")
    if "images" not in attachment["sticker"]:
      log.error("parse sticker attachment - not found tag 'images'")
      log.error(attachment["sticker"])
      return None
    # находим самый большой размер изображения:
    width=0
    height=0
    src=None
    data_item=None
    for item in attachment["sticker"]["images"]:
      if item["width"] > width:
        width=item["width"]
        height=item["height"]
        src=item["url"]
        data_item=item
        continue
      if item["height"] > height:
        width=item["width"]
        height=item["height"]
        src=item["url"]
        data_item=item
    if data_item == None:
      log.error("get src for sticker")
      log.error(attachment["sticker"])
    return data_item
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exceptions get_image_url_from_stiker_attachment()")
    log.error("json of attachment:")
    log.error(json.dumps(attachment, indent=4, sort_keys=True,ensure_ascii=False))
    return None

def get_photo_url_from_photo_attachment(attachment):
  global log
  try:
    log.debug("=start function=")
    if "sizes" not in attachment["photo"]:
      log.error("parse photo attachment - not found tag 'sizes'")
      log.error(attachment["photo"])
      return None
    # находим самый большой размер фото:
    width=0
    height=0
    src=None
    data_item=None
    for item in attachment["photo"]["sizes"]:
      if item["width"] > width:
        width=item["width"]
        height=item["height"]
        src=item["url"]
        data_item=item
        continue
      if item["height"] > height:
        width=item["width"]
        height=item["height"]
        src=item["url"]
        data_item=item
    if data_item == None:
      log.error("get src for photo")
      log.error(attachment["photo"])
    return data_item
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exceptions get_photo_url_from_photo_attachment()")
    log.error("json of attachment:")
    log.error(json.dumps(attachment, indent=4, sort_keys=True,ensure_ascii=False))
    return None

def create_matrix_format_reply_to_vk(mtxId, vkMessage, sendingUser, room_id, sender_id):
  msg = "<mx-reply><blockquote><a href=\"https://matrix.to/#/%s/%s\">In reply to "%(room_id,mtxId)
  msg+="%s:</a><br> %s</blockquote></mx-reply><br>"%(sendingUser,vkMessage)
  return msg


def proccess_vk_message(bot_control_room,room,user,sender_name,m):
  global data
  global lock
  global log
  try:
    log.debug("=start function=")
    send_status=False
    own_message=False
    text=""
    # Сообщение от нашей учётки в ВК:
    if m["out"]==1:
      log.debug("receive our message")
      log.debug("try lock() before access global data()")
      with lock:
        log.debug("success lock() before access global data")
        own_message=check_own_message_id(user,room,m["id"])
      log.debug("release lock() after access global data")
      if own_message == True:
        # id такой же, какой мы отправляли последнее время в этот диалог из матрицы - не отображаем его:
        log.debug("receive from vk our text, sended from matrix - skip it")
        return True
      else:
        # Это наше сообщение, но отправлено из другой клиентской программы. Шлём просто текст, но через m.notice, чтобы не дилинькал клиент:
        if len(m["text"])!=0:
          text="Вы: " + m["text"]
          if send_notice(room,text) == False:
            log.error("send_notice(%s)"%text)
            bot_system_message(user,"не смог отправить копию сообщения в комнату %s от самого себя (из ВК)"%room)
            return False
        elif "attachments" in m:
          if send_notice_about_attachments(user,room,sender_name,m["attachments"])==False:
            bot_system_message(user,'Ошибка: не смог отправить уведомления об отправленных мною же вложениях"')
        if "geo" in m:
          text="Вы отправили местоположение из другой клиентской программы"
          if send_notice(room,text) == False:
            log.error("send_notice(%s)"%text)
            bot_system_message(user,"не смог отправить копию сообщения в комнату %s от самого себя (из ВК)"%room)
            return False
        return True

    log.debug("1")
    if 'fwd_messages' in m and m['fwd_messages']!=[]:
      log.debug("1")
      if sender_name!=None:
        text+="<p><strong>%(sender_name)s</strong>:</p>\n"%{"sender_name":sender_name}
      # это ответ на сообщение - добавляем текст сообщения, на который дан ответ:
      for fwd in m['fwd_messages']:
        text+=create_reply_forward_text_for_matrix(user,fwd)
      text+="<p>%s</p>\n" % m["text"]
    elif 'reply_message' in m and m['reply_message']!=[]:
      log.debug("1")
      # это ответ на сообщение - добавляем текст сообщения, на который дан ответ:
      mtxReplyTo = retrieve_matrix_message_by_vk_id(m["reply_message"]["id"])
      if mtxReplyTo != None:
        fwd=m['reply_message']
        fwd_uid=fwd["from_id"]
        fwd_text=fwd["text"]
        user_profile=get_user_profile_by_uid(user,fwd_uid)
        fwd_user_name=fwd_uid
        if user_profile!=None:
          fwd_user_name=user_profile["first_name"] + " " + user_profile["last_name"]
          text+=create_matrix_format_reply_to_vk(mtxReplyTo, fwd_text, "<b>%s</b>"%(fwd_user_name), room, user)
        if sender_name!=None:
          text+="<p><strong>%(sender_name)s</strong>:</p>\n"%{"sender_name":sender_name}
      else:
        text+=create_reply_forward_text_for_matrix(user,m["reply_message"])
      text+="<p>%s</p>\n" % m["text"]
    else:
      log.debug("1")
      if sender_name!=None:
        text="<strong>%s</strong>: %s"%(sender_name,m["text"])
      else:
        text=m["text"]
    log.debug("1")

    if len(m["text"])>0:
      log.debug("send text='%s'"%text)
      event = send_html(room,text.replace('\n','<br>'), True) 
      if event != False:
        store_vk_message_by_matrix_id(m["id"], event["event_id"])
        send_status=True
      else:
        bot_system_message(user,"Ошибка: не смог отправить сообщение из ВК в комнату: '%s' сообщение были от: %s"%(room,sender_name))
        bot_system_message(user,"Содержимое сообщения: '%s'"%text)
        send_status=False
    # отправка вложений:
    if "attachments" in m:
      if send_attachments(user,room,sender_name,m["attachments"])==False:
        send_message(room,'Ошибка: не смог отправить вложения из исходного сообщения ВК - см. логи')
        bot_system_message(user,'Ошибка: не смог отправить вложения из исходного сообщения ВК - вложения были от: %s'%sender_name)
      else:
        send_status=True
    # отправка местоположения:
    if "geo" in m:
      if send_geo_to_matrix(room,sender_name,m["geo"])==False:
        send_message(room,'Ошибка: не смог отправить местоположение из исходного сообщения ВК - см. логи')
        bot_system_message(user,'Ошибка: не смог отправить местоположение из исходного сообщения ВК - местоположение было от: %s'%sender_name)
      else:
        send_status=True
    # события в комнате:
    if "action" in m:
      print(action)
      action=m["action"]
      selfAction=(len(m["profiles"]) == 1)
      if action["type"]=="chat_kick_user":
        if selfAction: 
          if send_notice(room,"Пользователь %s вышел из комнаты"%sender_name) == False:
            log.error("send_notice")
        else:
          if send_notice(room,"Пользователь %s кикнул из комнаты пользователя%s %s"%(sender_name, m["profiles"][1]["first_name"], m["profiles"][1]["last_name"])) == False:
            log.error("send_notice")
      elif action["type"]=="chat_invite_user":
        if selfAction:
          if send_notice(room,"Пользователь %s вошёл в комнату"%sender_name) == False:
            log.error("send_notice")
        else: 
          if send_notice(room,"Пользователь %s добавил в комнату пользователя%s %s"%(sender_name, m["profiles"][1]["first_name"], m["profiles"][1]["last_name"])) == False:
            log.error("send_notice")
      else:
        # TODO добавить обработчики других событий:
        if send_notice(room,"Неизвестный тип события (%s) для пользователя %s"%(action["type"],sender_name)) == False:
          log.error("send_notice")


    if send_status==False:
      matrix_room_name=get_name_of_matrix_room(room)
      if matrix_room_name==None:
        matrix_room_name=room
      bot_system_message(user,"Ошибка: не смог отправить сообщение в матрицу из ВК в комнату '%s'"%matrix_room_name)
      log.warning("сообщение было:")
      log.warning(m)

    return send_status
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    # log.error("exceptions in proccess_vk_message()")
    # bot_system_message(user,"при разборе сообщения из ВК - произошли ошибки - не смог принять сообщение. Обратитесь к разработчику.")
    # log.error("json of vk_message:")
    # log.error(json.dumps(m, indent=4, sort_keys=True,ensure_ascii=False))
    return False

def get_message_chat_type(conversations,peer_id):
  for conversation in conversations:
    if conversation["peer"]["id"] == peer_id:
      return conversation["peer"]["type"]
  return None

def vk_receiver_thread(user):
  global data
  global lock
  global log
  try:
    log.debug("=start function=")
    log.info("start new vk_receiver_thread() for user='%s'"%user)
    # Обновляем временные метки:
    log.debug("try lock() before access global data()")
    with lock:
      log.debug("success lock() before access global data")
      vk_id=data["users"][user]["vk"]["vk_id"]
    log.debug("release lock() after access global data")
    session = get_session(vk_id)
    log.info("update tses")
    ts,pts,key,server=get_tses(session)
    log.debug("try lock() before access global data()")
    with lock:
      log.debug("success lock() before access global data")
      update_vk_tses_data(data,user,ts,pts,key,server)
      bot_control_room=data["users"][user]["matrix_bot_data"]["control_room"]
    log.debug("release lock() after access global data")

    while True:
      log.debug("try exec get_new_vk_messages_v2(%s)"%user)
      res=get_new_vk_messages_v2(user)
      log.debug("end exec get_new_vk_messages_v2(%s)"%user)
      if res != None:
        log.debug("res=")
        log.debug(json.dumps(res, indent=4, sort_keys=True,ensure_ascii=False))
        conversations=res["conversations"]
        for m in res["messages"]:
          log.debug("Receive message from VK:")
          log.debug(json.dumps(m, indent=4, sort_keys=True,ensure_ascii=False))
          found_room=False
          for room in data["users"][user]["rooms"]:
            if "cur_dialog" in data["users"][user]["rooms"][room]:
              sender_name=None
              vk_room_id=m["peer_id"]
              # проверяем, групповой ли это чат:
              chat_type = get_message_chat_type(conversations, vk_room_id)
              if chat_type == None:
                log.error("get_message_chat_type(peer_id=%d)"%vk_room_id)

              if data["users"][user]["rooms"][room]["cur_dialog"]["id"] == vk_room_id:
                # нашли комнату:
                found_room=True
                if "pause" in data["users"][user]["rooms"][room]:
                  if data["users"][user]["rooms"][room]["pause"]==True:
                    log.info("receive message for paused room (%(room)s) - use command '!resume %(room)s' for receive messages to this room from VK"%{"room":room})
                    break

                # проверяем, групповой ли это чат:
                if chat_type == "chat":
                  # Если это групповой чат - нужно добавить имя отправителя, т.к. их там может быть много:
                  # Ищем отправителя в профилях полученного сообщения:
                  for profile in res["profiles"]:
                    if profile["id"]==m["from_id"]:
                      sender_name="<a href='https://vk.com/id%s'>%s %s </a>"%(profile["id"],profile["first_name"],profile["last_name"])
                if proccess_vk_message(bot_control_room,room,user,sender_name,m) == False:
                  log.warning("proccess_vk_message(room=%s) return false"%(room))
                # комнату нашли и сообщение в неё отправили - нет смысла перебирать оставшиеся комнаты
                break

          if found_room==False:
            # Не нашли созданной комнаты, чтобы отправить туда сообщение.
            # Нужно самим создать комнату и отправить туда сообщение.

            # Нужно найти имя диалога:
            dialogs=get_dialogs(data["users"][user]["vk"]["vk_id"])
            if dialogs == None:
              log.error("get_dialogs for user '%s'"%user)
              bot_system_message(user,'Не смог получить список бесед из ВК (обратитесь к разработчику), поэтому не смог создать новую комнату для связи с новым диалогом, попробуйте позже :-(')
              bot_system_message(user,"vk_uid отправителя='%d'"%m["peer_id"])
              bot_system_message(user,"Сообщение было: '%s'"%m["text"])
              continue

            cur_dialog=None
            if "chat_id" in m:
              # значит ищем среди групп:
              if m["chat_id"] in dialogs["chats"]:
                cur_dialog=dialogs["chats"][m["chat_id"]]
            else:
              # значит ищем среди чатов:
              if m["peer_id"] in dialogs["chats"]:
                cur_dialog=dialogs["chats"][m["peer_id"]]

            if cur_dialog == None:
              log.error("can not found VK sender in dialogs - logic error - skip")
              bot_system_message(user,"Не смог найти диалог для вновь поступившего сообщения. vk_uid отправителя='%d'"%m["peer_id"])
              bot_system_message(user,"Сообщение было: '%s'"%m["text"])
              continue

            # получаем фото пользователя ВК с которым устанавливаем мост:
            room_avatar_mx_url=None
            user_photo_url=vk_get_user_photo_url(session, cur_dialog["id"])
            user_photo_image_data=None
            if user_photo_url==None:
              log.error("get user vk profile photo for user_id=%d"%cur_dialog["id"])
            else:
              user_photo_image_data=get_data_from_url(user_photo_url)
              if user_photo_image_data==None:
                log.error("get image from url: %s"%user_photo_url)
            
            room_id=create_room(user,cur_dialog["title_ext"] + " (VK)",user_photo_image_data)
            if room_id==None:
              log.error("error create_room() for user '%s' for vk-dialog with vk-id '%d' ('%s')"%(user,cur_dialog["id"],cur_dialog["title"]))
              bot_system_message(user,"Не смог создать дополнительную комнату в Матрице: '%s' связанную с одноимённым диалогом в ВК"%cur_dialog["title"])
              continue
            bot_system_message(user,"Создал новую комнату Матрицы с именем: '%s (VK)' связанную с одноимённым диалогом в ВК"%cur_dialog["title"],notice=True)
            log.debug("try lock() before access global data()")
            with lock:
              log.debug("success lock() before access global data")
              data["users"][user]["rooms"][room_id]={}
              data["users"][user]["rooms"][room_id]["cur_dialog"]=cur_dialog
              data["users"][user]["rooms"][room_id]["state"]="dialog"
              data["users"][user]["rooms"][room_id]["last_matrix_owner_message"]=[]
              # сохраняем на диск:
              save_data(data)
            log.debug("release lock() after access global data")
            # отправляем текст во вновь созданную комнату:
            sender_name=None
            if "chat_id" in m:
              # Групповой чат - добавляем имя отправителя:
              # Ищем отправителя в профилях полученного сообщения:
              log.debug("try find user id = %d in profiles"%m["peer_id"])
              for profile in res["profiles"]:
                if profile["peer_id"]==m["peer_id"]:
                  sender_name="[%s]<strong>%s %s:</strong> "%(m["id"],profile["first_name"],profile["last_name"])
              if sender_name == None:
                log.warning("not found sender_name in profiles. Profiles was:")
                log.debug(json.dumps(res["profiles"], indent=4, sort_keys=True,ensure_ascii=False))

            if proccess_vk_message(bot_control_room,room_id,user,sender_name,m) == False:
              log.warning("proccess_vk_message(room=%s) return false"%room_id)

      # Проверка на необходимость выйти:
      exit_flag=False
      log.debug("try lock() before access global data()")
      with lock:
        log.debug("success lock() before access global data")
        if "exit" in data["users"][user]["vk"]:
          exit_flag=data["users"][user]["vk"]["exit"]
        if exit_flag==True:
          log.debug("set exit_flag for user '%s' to False"%user)
          data["users"][user]["vk"]["exit"]=False
      log.debug("release lock() after access global data")
      log.debug("thread: exit_flag=%d"%int(exit_flag))
      if exit_flag==True:
        log.info("get command to close thread for user %s - exit from thread..."%user)
        bot_system_message(user,"Завершаю процесс получения сообщений из ВК...")
        break
      # FIXME 
      #log.info("sleep main loop 1")
      #time.sleep(5)
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exceptions in vk_receiver_thread()")
    bot_system_message(user,"при получении сообщения ВК (в функции vk_receiver_thread() ) произошли ошибки. Не смог принять сообщения. Обратитесь к разработчику.")
    return False
  return True

def get_name_of_matrix_room(room_id):
  global client
  global log
  log.debug("=start function=")
  try:
    name=client.api.get_room_name(room_id)["name"]
    log.debug(name)
    log.debug("name of %s = %s"%(room_id,name))
    return name
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exceptions in get_name_of_matrix_room()")
    log.error("error get name of MATRIX room: %s"%room_id)
    return None

def vk_get_user_photo_url(session, user_id):
  global log
  try:
    log.debug("=start function=")
    api = vk.API(session, v=VK_API_VERSION)
    response=api.users.get(user_ids="%d"%user_id,fields="photo_max")
    url=response[0]["photo_max"]
    log.debug(json.dumps(response, indent=4, sort_keys=True,ensure_ascii=False))
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute vk_get_user_photo()")
    log.error("API or network error")
    return None
  return url

def set_matrix_room_avatar(room_id, image_data):
  global client
  try:
    log.debug("=start function=")
    # загружаем картинку в матрицу и получаем mx_url:
    room_avatar_mx_url=upload_file(image_data,"image/jpeg")
    if room_avatar_mx_url == None:
      log.error("uload file to matrix server")
      return None

    """Perform PUT /rooms/$room_id/state/m.room.avatar
    """
        #"info": {
        #  "mimetype": "image/jpeg"
        #},
    body = {
        "url":"%s"%room_avatar_mx_url
    }
    return client.api.send_state_event(room_id, "m.room.avatar", body, timestamp=None)
  except Exception as e:
    log.error(get_exception_traceback_descr(e))
    log.error("exception at execute set_matrix_room_avatar()")
    return None

if __name__ == '__main__':
  log= logging.getLogger("MatrixVkBot")
  if conf.debug:
    log.setLevel(logging.DEBUG)
  else:
    log.setLevel(logging.INFO)

  # create the logging file handler
  #fh = logging.FileHandler(conf.log_path)
  fh = logging.handlers.TimedRotatingFileHandler(conf.log_path, when=conf.log_backup_when, backupCount=conf.log_backup_count, encoding='utf-8')
  formatter = logging.Formatter('%(asctime)s - %(name)s - %(filename)s:%(lineno)d - %(funcName)s() %(levelname)s - %(message)s')
  fh.setFormatter(formatter)

  if conf.debug:
    # логирование в консоль:
    #stdout = logging.FileHandler("/dev/stdout")
    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(formatter)
    log.addHandler(stdout)

  # add handler to logger object
  log.addHandler(fh)

  log.info("Program started")
  main()
  log.info("Program exit!")
