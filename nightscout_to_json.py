"""
Small program to download last N days from Nightscout
and put them into the format the tune program
(https://github.com/mariusae/tune)expects.
"""
"""
  (c) Jan Dittmer <jdi@l4x.org> 2021

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

from datetime import datetime, timedelta, date
import argparse
import dateutil.parser
import hashlib
import copy
import collections
import json
import pytz
import sys
import time
import requests
import pytz
import numpy as np
from pprint import pprint


TZ='Europe/Berlin' 


class Nightscout(object):

  def __init__(self, url, secret=None):
    self.url = url
    self.secret = None
    if secret:
        self.secret = hashlib.sha1(secret.encode('utf-8')).hexdigest()
    self.batch = []


  def download(self, path, params=None):
    url = self.url + '/api/v1/' + path + '.json'
    headers = {
            'Content-Type': 'application/json',
    }
    if self.secret:
        headers.update({
            'api-secret': self.secret,
        })
    response = requests.get(url, params=params, headers=headers)
    if response.status_code != 200:
        print(response.status_code, response.text)
        raise Exception(response.status_code, response.text)
    return response.json()

  def convert(self, profile, entries, treatments):
    ps = profile[0]['store']['Default']
    tz = pytz.timezone(ps['timezone'])
    common = {
            'version': 1,
            'timezone': ps['timezone'],
            'minimum_time_interval': 3600,
            'maximum_schedule_item_count': 24,
        #    'allowed_basal_rates': [n/10.0 for n in range(1, 20)],
        #    'tuning_limit': 0.4,
            'basal_insulin_parameters': {
                # +- Fiasp, not sure about duration
                'delay': 8,
                'peak': 44,
                'duration': 200,
            },
           'timelines': [],
    }
    ret = copy.deepcopy(common)
    ret.update({
            'insulin_sensitivity_schedule': {
                'index': [int(x['timeAsSeconds'] / 60) for x in ps['sens']],
                'values': [x['value'] for x in ps['sens']],
            },
            'carb_ratio_schedule': {
                'index': [int(x['timeAsSeconds'] / 60) for x in ps['carbratio']],
                'values': [x['value'] for x in ps['carbratio']],
            },
            'basal_rate_schedule': {
                'index': [int(x['timeAsSeconds'] / 60) for x in ps['basal']],
                'values': [x['value'] for x in ps['basal']],
            },
    }) 

    def lookup(hour, schedule):
        minutes = hour * 60
        for i, v in enumerate(schedule['index']):
            if v >= minutes:
                return schedule['values'][i]
        return schedule['values'][-1]


    def lookup_basal(hour):
        return lookup(hour, ret['basal_rate_schedule'])

    def lookup_carbs(hour):
        return lookup(hour, ret['carb_ratio_schedule'])

    def lookup_isf(hour):
        return lookup(hour, ret['insulin_sensitivity_schedule'])

    def encode(series):
        o = 0
        for i, v in enumerate(series):
            series[i] -= o
            o = v

    buckets = {
       'start_ts': None,
       'end_ts': None,
       'size': 300,
       'hours': [],
       'glucose': [],
       'insulin': [],
       'carbs': [],
    }

    basal_default_timeline = {
            'type': 'basal',
            'parameters': ret['basal_insulin_parameters'],
            'index': [],
            'values': [],
            'durations': [],
    }

    glucose = {
            'type': 'glucose',
            'index': [],
            'values': [],
	    'hours': [],
    }
    start_ts = None
    min_dt = None
    max_dt = None
    offset = None
    offset_sgv = None
    for e in sorted(entries, key=lambda x: x['dateString']):
        dt = dateutil.parser.parse(e['dateString'])
        lt = dt.astimezone(tz)
        ots = int(datetime.timestamp(dt))
        # print(e['dateString'], dt)
        min_dt = min(min_dt or dt, dt)
        max_dt = max(max_dt or dt, dt)
        glucose['index'].append(ots)
        glucose['values'].append(e['sgv'])
        glucose['hours'].append(lt.hour)

        if len(glucose['index']) >= 2:
            default_basal = lookup_basal(lt.hour)
            basal_default_timeline['index'].append(glucose['index'][-2])
            basal_default_timeline['values'].append(default_basal)
            basal_default_timeline['durations'].append(ots - glucose['index'][-2])
    print('MIN', min_dt, 'MAX', max_dt)
    min_ts = int(datetime.timestamp(min_dt))
    max_ts = int(datetime.timestamp(max_dt))
    bucket_size = 300

    nbuckets = (max_ts - min_ts) // bucket_size
    new_timeline = np.array([min_ts + i*bucket_size for i in range(nbuckets)])
    new_glucose = np.interp(new_timeline, glucose['index'], glucose['values'])

    # new_hours = np.zeros(nbuckets)
    new_hours = np.interp(new_timeline, glucose['index'], glucose['hours'])

    new_prog_basal = np.array([lookup_basal(int(h))*bucket_size/3600 for h in new_hours])
    new_bolus = np.zeros(nbuckets)
    new_carbs = np.zeros(nbuckets) 
    new_basal = np.zeros(nbuckets)

    def get_bucket(ts):
       return (ts - min_ts) // bucket_size

    encode(glucose['index'])
    encode(glucose['values'])
    encode(glucose['hours'])
    ret['timelines'].append(glucose)
    encode(basal_default_timeline['index'])
    encode(basal_default_timeline['values'])
    encode(basal_default_timeline['durations'])
    ret['timelines'].append(basal_default_timeline)

    basal = []
    bolus = []
    carbs = collections.defaultdict(list)
    for t in sorted(treatments, key=lambda x: x['created_at']):
        dt = dateutil.parser.parse(t['created_at'])
        lt = dt.astimezone(tz)
        ts = int(datetime.timestamp(dt))
        if t['eventType'] == 'Temp Basal':
           # if the temp basal is longer than the schedule,
           # needs to split up in 30 minute intervals.
           default_basal = lookup_basal(lt.hour)
           delta = t['rate'] - default_basal
           basal.append((ts, delta, t['duration']*60, t['rate'], lt))
        elif t['eventType'] == 'Correction Bolus':
           bolus.append((ts, t['insulin']))
        elif t['eventType'] == 'Meal Bolus':
           carbs[t['absorptionTime']].append((ts, t['carbs']))
        elif t['eventType'].startswith('Debug.'):
            pass
        else:
           print('ignored', t['eventType'])
    
    basal_timeline = {
            'type': 'basal',
            'parameters': ret['basal_insulin_parameters'],
            'index': [],
            'values': [],
            'durations': [],
            'ots': [],
            'lt': [],
            'rate': [],
    }
    offset = None
    active_until = None
    for ts, rate, duration, rate, lt in basal:
        ots = ts

        if duration == 0:
            if not basal_timeline['index']:
                    continue
            delta = ots - basal_timeline['index'][-1]
            basal_timeline['durations'][-1] = delta
            active_until = None
            continue

        if active_until and active_until >= ots:
            # End previous dose
            delta = ots - basal_timeline['index'][-1]
            basal_timeline['durations'][-1] = delta

        if len(basal_timeline['index']) and ts == basal_timeline['index'][-1]:
            print('overwrite duplicate basal ts', ts)
            basal_timeline['durations'][-1] = duration
            basal_timeline['values'][-1] = rate
        else:
            basal_timeline['index'].append(ots)
            basal_timeline['values'].append(rate)
            basal_timeline['durations'].append(duration)
            basal_timeline['lt'].append(lt)
            basal_timeline['rate'].append(rate)
        active_until = ots + duration

    for ts, _, duration, rate, lt in zip(basal_timeline['index'], basal_timeline['values'],
                                   basal_timeline['durations'], basal_timeline['rate'],
                                   basal_timeline['lt']):
       i = 0
       bucket = get_bucket(ts)
       while duration > 0:
          value = rate - lookup_basal(lt.hour)
          p = value / 3600 * min(bucket_size, duration)
          # print(lt.hour, duration, lookup_basal(lt.hour), rate, value, p)
          if bucket + i < len(new_basal):
               new_basal[bucket + i] += p
          else:
               break
          duration -= bucket_size
          i += 1
          lt += timedelta(seconds=bucket_size)
    del basal_timeline['lt']
    del basal_timeline['rate']
    encode(basal_timeline['index'])
    encode(basal_timeline['values'])
    encode(basal_timeline['durations'])
    ret['timelines'].append(basal_timeline)

    bolus_timeline = {
            'type': 'bolus',
            'parameters': ret['basal_insulin_parameters'],
            'index': [],
            'values': [],
    }
    offset = None
    for ts, units in bolus:
        ots = ts
        if bolus_timeline['index'] and ts == bolus_timeline['index'][-1]:
            print('drop duplicate bolus ts', ts)
            continue
        bolus_timeline['index'].append(ots)
        bolus_timeline['values'].append(units)
        bucket = get_bucket(ts)
        new_bolus[bucket] += units

    encode(bolus_timeline['index'])
    encode(bolus_timeline['values'])
    ret['timelines'].append(bolus_timeline)

    new_carbs = {}
    for absorption, items in carbs.items():
        carb_timeline = {
            'type': 'carb',
            'parameters': { 'delay': 5.0, 'duration': absorption },
            'index': [],
            'values': [],
        }
        offset = None

        nc = np.zeros(nbuckets) 
        for ts, amount in items:
            ots = ts
            #if len(carb_timeline['index']) and ts == carb_timeline['index'][-1]:
            #    print('tweak duplicate carb ts', ts)
            #    ts += 1
            bucket = get_bucket(ts)
            nc[bucket] += amount
            carb_timeline['index'].append(ots)
            carb_timeline['values'].append(amount)
        encode(carb_timeline['index'])
        encode(carb_timeline['values'])
        ret['timelines'].append(carb_timeline)
        new_carbs[absorption] = nc.tolist()

    new = {
    'size': bucket_size,

    'carb_ratios': [lookup_carbs(h) for h in range(24)],
    'isf': [lookup_isf(h) for h in range(24)],
    'basal_rates': [lookup_basal(h) for h in range(24)],

    'timeline': new_timeline.tolist(),
    'glucose': new_glucose.tolist(),
    'hours': [int(h) for h in new_hours.tolist()],
    'prog_basal': new_prog_basal.tolist(),
    'bolus': new_bolus.tolist(),
    'basal': new_basal.tolist(),
    'carbs': new_carbs,
    }
    for v in new_basal + new_prog_basal:
       if v < 0:
          print(v)
    print('total net basal', sum(new_basal))
    print('total prog basal', sum(new_prog_basal))
    print('total basal', sum(new_prog_basal) + sum(new_basal), min(new_basal))
    print('total bolus', sum(new_bolus))
    print('total carbs', sum(new_carbs))
    new.update(common)


    return ret, new


if __name__ == '__main__':

  parser = argparse.ArgumentParser()
  parser.add_argument("--url", type=str, help="nightscout url")
  parser.add_argument("--secret", type=str, help="nightscout secret")
  parser.add_argument("--days", type=int, help="days to retrieve since yesterday")
  args = parser.parse_args()

  days = int(args.days or 1)

  today = datetime.combine(date.today(), datetime.min.time())
  dl = Nightscout(args.url, args.secret)
  
  cache_fn = 'cache_%s_%d.json' % (today.isoformat(), days)
  j = {}
  try:
    j = json.loads(open(cache_fn).read())
  except IOError:
    pass

  profile = j.get('p') or dl.download('profile')
  tz = profile[0]['store']['Default']['timezone']
  #today = today.replace(tzinfo=pytz.timezone(tz))
  today = today.astimezone(pytz.timezone(tz))
  startdate = today - timedelta(days=days + 1)
  enddate = startdate + timedelta(days=days) 
  startdate = startdate.astimezone(pytz.utc).isoformat()
  enddate = enddate.astimezone(pytz.utc).isoformat()
  print(startdate, enddate)

  treatments = j.get('t') or dl.download(
          'treatments',
          {'find[created_at][$gte]': startdate, 'find[created_at][$lte]': enddate})
  entries = j.get('e') or dl.download(
          'entries',
          {'find[dateString][$gte]': startdate, 'find[dateString][$lte]:': enddate, 'count': '10000'})
  if not j:
    open(cache_fn, 'w').write(json.dumps({'p': profile, 'e': entries, 't': treatments}, indent=4, sort_keys=True))
  ret, new = dl.convert(profile, entries, treatments)
  output_fn = 'ret_%s_%s.json' % (startdate, enddate)
  open(output_fn, 'w').write(json.dumps(ret, indent=4, sort_keys=True))

  new_fn = 'new_%s_%s.json' % (startdate, enddate)
  open(new_fn, 'w').write(json.dumps(new, indent=4, sort_keys=True))
  print('Written', new_fn)
