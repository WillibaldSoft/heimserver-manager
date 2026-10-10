import unittest
from types import SimpleNamespace
from unittest.mock import patch
from flask import Flask,session
from modules import offline_files as m
class Selection(unittest.TestCase):
 def test_only_permitted_folders_are_rendered(self):
  con=SimpleNamespace(close=lambda:None,execute=lambda *a:[dict(id=1,name='User / PC',ip='192.0.2.1')])
  app=Flask(__name__);app.secret_key='test'
  m.register(app,SimpleNamespace(db=lambda:con,page=lambda title,body,section:body))
  @app.before_request
  def csrf():session['auth_csrf']='test'
  def permit(path,*a):
   if path=='/data/denied':raise ValueError('denied')
   return False
  with patch.object(m,'grants',return_value=[]),patch.object(m.storage,'mounts',return_value=[]),patch.object(m.storage,'server_choices',return_value=['/data/allowed','/data/denied']),patch('modules.heimnetz_clients.init_tables'),patch('modules.heimnetz_extra.client_bindings.schema'),patch('modules.offline_files.rights.identity',return_value=object()),patch('modules.offline_files.rights.permission',side_effect=permit),patch('modules.offline_files.dispatch.invoke'),patch.object(m.os,'stat',return_value=SimpleNamespace(st_dev=1,st_ino=2)):
   text=app.test_client().get('/clients/offline?client=1').get_data(as_text=True)
   self.assertIn("value='/data/allowed'",text);self.assertNotIn("value='/data/denied'",text)
