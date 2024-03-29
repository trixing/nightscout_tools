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
MGDL='mg/dl'

MGDL_TO_MMOL = 18.0
RANGE_LOW = 70
RANGE_HIGH = 180


class DownloadError(Exception):
    pass


class Nightscout(object):

  def __init__(self, url, secret=None, token=None, hashed_secret=None):
    self.url = url
    self.secret = None
    self.token = token
    if hashed_secret:
        self.secret = hashed_secret
    elif secret:
        self.secret = hashlib.sha1(secret.encode('utf-8')).hexdigest()
    self.batch = []


  def download(self, path, params=None):
    url = self.url + '/api/v1/' + path + '.json'
    headers = {
            'Content-Type': 'application/json',
    }
    if self.secret or self.token:
        headers.update({
            'api-secret': self.secret or self.token,
        })

    params = params or {}

    response = requests.get(url, params=params, headers=headers)
    if response.status_code != 200:
        print('Server Error', response.status_code, response.text)
        raise DownloadError(response.status_code, response.text)
    return response.json()

  def convert(self, startdate, enddate,
              profile, entries, treatments, tz,
              bucket_size=None):
    if not bucket_size:
        bucket_size = 300
    log = []
    defaultProfile = profile[0]['defaultProfile']
    ps = profile[0]['store'][defaultProfile]
    bg_units = ps.get('units', profile[0].get('units', MGDL))
    tz = pytz.timezone(ps['timezone'])
    common = {
            'version': 1,
            'timezone': ps['timezone'],
            'units': bg_units,
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
    def seconds(x):
        # see https://github.com/nightscout/cgm-remote-monitor/blob/46418c7ff275ae80de457209c1686811e033b5dd/lib/profilefunctions.js#L58
        if 'time' in x:
            p = x['time'].split(':')
            if len(p) == 2:
                return int(p[0])*3600 + int(p[1])*60
        if 'timeAsSeconds' in x:
            return int(x['timeAsSeconds'])
        return 0

    ret.update({
            'insulin_sensitivity_schedule': {
                'index': [seconds(x)/60 for x in ps['sens']],
                'values': [x['value'] for x in ps['sens']],
            },
            'carb_ratio_schedule': {
                'index': [seconds(x)/60 for x in ps['carbratio']],
                'values': [x['value'] for x in ps['carbratio']],
            },
            'basal_rate_schedule': {
                'index': [seconds(x)/60 for x in ps['basal']],
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
        if 'sgv' not in e:
            log.append('glucose entry without glucose value: %s' % repr(e))
            continue
        glucose['index'].append(ots)
        glucose['values'].append(e['sgv'])
        glucose['hours'].append(lt.hour + (lt.minute*60 + lt.second)/3600.0)

        if len(glucose['index']) >= 2:
            default_basal = lookup_basal(lt.hour)
            basal_default_timeline['index'].append(glucose['index'][-2])
            basal_default_timeline['values'].append(default_basal)
            basal_default_timeline['durations'].append(ots - glucose['index'][-2])
    # min_ts = int(datetime.timestamp(min_dt))
    # max_ts = int(datetime.timestamp(max_dt))
    min_ts = int(datetime.timestamp(startdate))
    max_ts = int(datetime.timestamp(enddate))

    nbuckets = (max_ts - min_ts) // bucket_size
    new_timeline = np.array([min_ts + i*bucket_size for i in range(nbuckets)])
    new_glucose = np.interp(new_timeline, glucose['index'], glucose['values'])

    # new_hours = np.zeros(nbuckets)
    new_hours = np.interp(new_timeline, glucose['index'], glucose['hours'])

    new_prog_basal = np.array([lookup_basal(int(h))*bucket_size/3600 for h in new_hours])
    new_bolus = np.zeros(nbuckets)
    new_carbs = np.zeros(nbuckets)
    new_basal = np.zeros(nbuckets)

    new_iage = np.zeros(nbuckets)
    new_cage = np.zeros(nbuckets)
    new_sage = np.zeros(nbuckets)

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
    cage = []
    iage = []
    sage = []
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
        elif t['eventType'] == 'Bolus':
           bolus.append((ts, t['insulin']))
        elif t['eventType'] == 'Meal Bolus':
           carbs[t['absorptionTime']].append((ts, t['carbs']))
        elif t['eventType'] == 'Carb Correction':
           carbs[t.get('absorptionTime', 180)].append((ts, t['carbs']))
        elif t['eventType'].startswith('Debug.'):
            pass
        elif t['eventType'] == 'Site Change':
            cage.append((ts, True))
        elif t['eventType'] == 'Insulin Change':
            iage.append((ts, True))
        elif t['eventType'] in ('Sensor Change', 'Sensor Start',):
            sage.append((ts, True))
        elif t['eventType'].startswith('Log.'):
            pass
        else:
           print('ignored', t['eventType'])
           pass

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
            log.append('overwrite duplicate basal ts: %d' % ts)
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
              if bucket + i >= 0:
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
            log.append('drop duplicate bolus ts', ts)
            continue
        bolus_timeline['index'].append(ots)
        bolus_timeline['values'].append(units)
        bucket = get_bucket(ts)
        if bucket < len(new_bolus) and bucket >= 0:
            new_bolus[bucket] += units
        else:
            log.append('Found bolus out of bounds: ts %d, units %.2f, last bucket %d, max_ts %d' % (ts, units, len(new_bolus), max_ts))

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
            if bucket < len(nc) and bucket >= 0:
                nc[bucket] += amount
            else:
                log.append('Found carb entry out of bounds: ts %d, max_ts %d, carbs %f' % (ts, max_ts, amount))
            carb_timeline['index'].append(ots)
            carb_timeline['values'].append(amount)
        encode(carb_timeline['index'])
        encode(carb_timeline['values'])
        ret['timelines'].append(carb_timeline)
        new_carbs[absorption] = nc.tolist()


    for src, target in ((iage, new_iage), (cage, new_cage), (sage, new_sage)):
        for ts, _ in src:
            bucket = get_bucket(ts)
            if bucket < len(target) and bucket >= 0:
                target[bucket] = 1
        age = -1
        for i, v in enumerate(target):
            if age >= 0:
                age += bucket_size
            elif v == 1:
                age = 0
            target[i] = age



    new = {
    'size': bucket_size,
    'tz': str(tz),
    'units': bg_units,

    'carb_ratios': [lookup_carbs(h) for h in range(24)],
    'isf': [lookup_isf(h) for h in range(24)],
    'basal_rates': [lookup_basal(h) for h in range(24)],

    'timeline': new_timeline.tolist(),
    'glucose': new_glucose.tolist(),
    'hours': new_hours.tolist(),
    'prog_basal': new_prog_basal.tolist(),
    'bolus': new_bolus.tolist(),
    'basal': new_basal.tolist(),
    'carbs': new_carbs,
    'iage': new_iage.tolist(),
    'cage': new_cage.tolist(),
    'sage': new_sage.tolist(),
    }
    new['insulin'] = []
    for i in range(len(new['bolus'])):
        new['insulin'].append(
            new['bolus'][i] + new['basal'][i] + new['prog_basal'][i])
    for v in new_basal + new_prog_basal:
       if v < -0.1:
          log.append(v)
    log.append('total net basal: %.1f U' % sum(new_basal))
    log.append('total prog basal: %.1f U' % sum(new_prog_basal))
    log.append('total basal: %.1f U %.1f' % (sum(new_prog_basal) + sum(new_basal), min(new_basal)))
    log.append('total bolus: %.1f U' % (sum(new_bolus)))
    for absorption, x in new['carbs'].items():
        log.append('total carbs %d min: %d g' % (absorption, sum(x)))
    new.update(common)
    return ret, new, log


class Stats(dict):

    def add(self, other):
        for x, v in other.items():
            self[x] = self.get(x, 0) + v

    def __add__(self, other):
        return self.__radd__(other)

    def __radd__(self, other):
        s = Stats()
        for x, v in self.items():
            if type(v) in (float, int):
                s[x] = v

        if type(other) in (Stats, dict):
            for x, v in other.items():
                if type(v) in (float, int):
                    s[x] = s.get(x, 0) + v

        return s

    def format(self, other=None, norm=1):
        r = {}
        for k, v in self.items():
            if k in ('insulin', 'carbs',
                     'basal', 'prog_basal'):
                r[k] = round(v/norm, 1)
            elif k in ('glucose',):
                avg = v/self.get('samples', 1)
                r[k] = round(avg, 1)
                units = self.get('units', MGDL)
                avg_mgdl = avg if units == MGDL else avg * MGDL_TO_MMOL
                r['a1c'] = round((avg_mgdl + 46.7) / 28.7, 1)
            elif k in ('range_low', 'range_high', ):
                r[k] = round(100 * v/self.get('samples', 1), 1)
            elif k in ('samples', 'units', ):
                pass
            else:
                r[k] = v
        if other:
            r.update(other)
        return r


def stats(new):
    bg_units = new['units']
    j = {
      'tz': new['tz'],
      'units': bg_units
    }

    overall = Stats()
    daily = []
    stats = {}
    stats_hourly = {}
    stats_wd_hourly = {}
    wd_count = {}
    for i in range(24):
        stats_hourly[i] = Stats()
        for wd in range(7):
            stats_wd_hourly[(wd, i)] = Stats()
            wd_count[wd] = 0


    lastdate = None
    range_low = RANGE_LOW
    range_high = RANGE_HIGH
    if bg_units != MGDL:
        range_low = range_low / MGDL_TO_MMOL
        range_high = range_high / MGDL_TO_MMOL
    day = Stats()
    for i, t in enumerate(new['timeline']):
        dt = datetime.fromtimestamp(new['timeline'][i])
        if not lastdate or dt.date() != lastdate:
            if lastdate:
                day.update({
                    'date': lastdate.isoformat(),
                    'weekday': lastdate.strftime('%a'),
                })
                daily.append(day)
            lastdate = dt.date()
            wd_count[lastdate.weekday()] += 1
            day = Stats()

        point = Stats(
            glucose = new['glucose'][i],
            range_low = 1 if new['glucose'][i] < range_low else 0,
            range_high = 1 if new['glucose'][i] > range_high else 0,
            insulin = new['insulin'][i],
            carbs = sum(x[i] for x in new['carbs'].values()),
            basal = new['basal'][i] + new['prog_basal'][i],
            prog_basal = new['prog_basal'][i],
            samples = 1)

        wd = lastdate.weekday()
        hour = int(new['hours'][i])

        stats_hourly[hour].add(point)
        stats_wd_hourly[(wd, hour)].add(point)

        day.add(point)
        overall.add(point)

    day.update({
        'date': lastdate.isoformat(),
        'weekday': lastdate.strftime('%a'),
    })
    daily.append(day)
    days = len(daily)

    insulin = [x['insulin'] for x in daily]
    if insulin:
        j['tdd'] = {
            'avg': round(sum(insulin)/len(insulin), 1),
            'weighted': round(0.6*sum(insulin)/len(insulin) + 0.4*insulin[-1], 1),
            'yesterday': round(insulin[-1], 1)
        }
    j['overall'] = {
        'total': overall.format({'days': days}),
        'daily_average': sum(daily).format({'days': days}, days)
    }
    j['daily'] = [day.format() for day in daily]
    j['hourly'] = [stats_hourly[i].format({'hour': i}, days) for i in range(24)]


    week = (0, 1, 2, 3, 4)
    weekend = (5, 6)

    dayparts = dict(
        Night = (0, 1, 2, 3, 4, 5, 21, 22, 23),
        Breakfast = (6, 7, 8, 9),
        Snack = (10, 11),
        Lunch = (12, 13),
        SnackAfternoon = (14, 15, 16, 17),
        Dinner = (18, 19, 20)
    )

    j['pattern'] = {}
    for (desc, days) in (('Week', week), ('Weekend', weekend)):
        j['pattern'][desc] = []
        allday = Stats()
        for part, hours in dayparts.items():
            daypart = Stats()
            daycount = 0
            for wd in days:
                for h in hours:
                    daypart += stats_wd_hourly[(wd, h)]
                daycount += wd_count[wd]

            if daycount > 0:
                j['pattern'][desc].append(daypart.format({
                    'daytime': part,
                }, daycount))

            allday.add(daypart)

        alldaycount = sum(v for wd, v in wd_count.items() if wd in days)
        if alldaycount > 0:
            j['pattern'][desc].append(allday.format({
                'daytime': 'Daily',
            }, alldaycount))

    # for debugging mostly
    j['weekdays'] = wd_count
    return j


def run(url, start, end, days, cache=True, token=None, hashed_secret=None,
        bucket_size=None):
  today = datetime.combine(date.today(), datetime.min.time())
  dl = Nightscout(url, secret=None, token=token, hashed_secret=hashed_secret)
  host = url.replace('https://', '').replace('http://', '')
  cache_fn = 'cache_%s_%s_%d.json' % (host, today.isoformat(), days)
  j = {}
  try:
    j = json.loads(open(cache_fn).read())
  except IOError:
    pass

  profile = j.get('p') or dl.download('profile')
  defaultProfile = profile[0]['defaultProfile']
  tz = profile[0]['store'][defaultProfile]['timezone']
  #today = today.replace(tzinfo=pytz.timezone(tz))
  today = today.astimezone(pytz.timezone(tz))

  startdate = today - timedelta(days=days)
  enddate = startdate + timedelta(days=days)

  # Retrieve slightly more than necessary to account for
  # temp basals starting the previous day
  startdate_ns = (startdate - timedelta(hours=2)).astimezone(pytz.utc).isoformat()
  enddate_ns = (enddate + timedelta(hours=1)).astimezone(pytz.utc).isoformat()

  treatments = j.get('t') or dl.download(
          'treatments',
          {'find[created_at][$gte]': startdate_ns, 'find[created_at][$lte]':
          enddate_ns, 'count': '10000'})
  entries = j.get('e') or dl.download(
          'entries',
          {'find[dateString][$gte]': startdate_ns, 'find[dateString][$lte]:':
          enddate_ns, 'count': '10000'})
  if not j and cache:
    open(cache_fn, 'w').write(json.dumps({'p': profile, 'e': entries, 't': treatments}, indent=4, sort_keys=True))
  return dl.convert(startdate, enddate, profile, entries, treatments, tz, bucket_size=bucket_size)


if __name__ == '__main__':

  parser = argparse.ArgumentParser()
  parser.add_argument("--url", type=str, help="nightscout url")
  parser.add_argument("--secret", type=str, help="nightscout secret")
  parser.add_argument("--days", type=int, help="days to retrieve since yesterday")
  args = parser.parse_args()

  ret, new, log = run(args.url, None, None, days=args.days)

  output_fn = 'ret_%s_%s.json' % (startdate, enddate)
  open(output_fn, 'w').write(json.dumps(ret, indent=4, sort_keys=True))

  new_fn = 'new_%s_%s.json' % (startdate, enddate)
  open(new_fn, 'w').write(json.dumps(new, indent=4, sort_keys=True))
  print('')
  print('Written', new_fn)

  j = stats(new)
  print(json.dumps(j, indent=4))
