"""
  Python Library to interact with Nightscout Diabetes Management tool
"""
"""
  Released under MIT license. See the accompanying LICENSE.txt file for
  full terms and conditions

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
  THE SOFTWARE.
"""

import datetime
import hashlib
import json
import os
import pytz
import urllib
import urllib2


class NoData(object):
  pass


class NightscoutUploader(object):

  def __init__(self, url=None, secret=None, device=None):
    self.url = url or os.environ.get('NIGHTSCOUT_URL')
    self.secret = hashlib.sha1(secret or os.environ.get('NIGHTSCOUT_SECRET')).hexdigest()
    self.batch = []
    self.device = device or 'nightscout_uploader_py'

  def upload(self, path, data):
    batch = []
    for item in data:
      batch.append(item)
      # Some rate limiting
      if len(batch) >= 1000:
        self._upload(path, batch)
        time.sleep(5)
        batch = []
    return self._upload(path, batch)

  def _upload(self, path, data):
    if not data:
      return NoData
    req = urllib2.Request(self.url + '/api/v1/' + path + '/')
    req.add_header('Content-Type', 'application/json')
    req.add_header('api-secret', self.secret)
    print 'Upload batch', path, len(data)
    response = urllib2.urlopen(req, json.dumps(data))
    return response

  def date(self, date):
    try:
      utc = date.astimezone(pytz.utc)
      local = date.replace(tzinfo=None)
    except ValueError:
      utc = date
      local = date
    # No idea what I'm doing...
    # sec = int(1000*(time.mktime(date.timetuple())-7200))
    # sec = int(1000*(time.mktime(date.timetuple())))
    sec = int(1000*(local - datetime.datetime(1970, 1, 1)).total_seconds())
    x = {'date': sec,
         'dateString': local.strftime('%Y-%m-%dT%H:%M:%SZ')}
    # print date, x
    return x

  def upload_glucose(self, data, data_type):
      return self.upload('entries', self._glucose(data, data_type)) 

  def _glucose(self, data, data_type):
    upload_data = []
    for date, value, units in data:
      d = self.date(date)
      d.update({
          data_type: int(value),
          'type': data_type,
          'device': self.device,
          'notes': units,
      })
      yield d

  def upload_carbs(self, data):
    return self.upload('treatments', self._carbs(data)) 

  def _carbs(self, data):
    for date, value in data:
      d = self.date(date)
      d = {
          'created_at': d['dateString'],
          'timestamp': d['dateString'],
          'eventType': 'Meal Bolus',
          'enteredBy': self.device,
          'carbs': value
      }
      yield d

  def upload_bolus(self, data):
    return self.upload('treatments', self._bolus(data))

  def _bolus(self, data):
    for date, bolus in data:
      d = self.date(date)
      assert bolus.type == 'Normal'
      d = {
          'created_at': d['dateString'],
          'timestamp': d['dateString'],
          'eventType': 'Correction Bolus',
          'enteredBy': self.device,
          'insulin': bolus.volume,
          'programmed': bolus.volume,
          'type': 'normal',
          'duration': 0,
      }
      yield d

  def upload_basal(self, data):
    return self.upload('treatments', self._basal(data))

  def _basal(self, data):
    first = data.next()
    batch = []
    while True:
      (date, basal) = first
      try:
        next = data.next()
      except StopIteration:
        break
      duration = (next[0] - date).total_seconds()
      d = self.date(date)
      d = {
          'created_at': d['dateString'],
          'timestamp': d['dateString'],
          'eventType': 'Temp Basal',
          'enteredBy': self.device,
          'absolute': basal,
          'rate': basal,
          'duration': int(duration) / 60,  # minutes!!
      }
      yield d
      first = next

  def upload_exercise(self, data):
    return self.upload('treatments', self._exercise(data)) 

  def _exercise(self, data):
    for date, value in data:
      date = date
      d = self.date(date)
      d = {
          'id': value['id'],
          'created_at': d['dateString'],
          'timestamp': d['dateString'],
          'eventType': 'Exercise',
          # Hack to store the details somewhere
          'enteredBy': 'jawbone: ' + value['details'],
          'duration': value['duration'],
          'notes': value['notes'],
      }
      yield d

  def upload_notes(self, data):
    return self.upload('treatments', self._notes(data))

  def _notes(self, data):
    for date, value in data:
      date = date
      d = self.date(date)
      d = {
          'created_at': d['dateString'],
          'timestamp': d['dateString'],
          'eventType': 'Note',
          'enteredBy': self.device,
      }
      d.update(value)
      yield d

