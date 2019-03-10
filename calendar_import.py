USAGE = """
  Short script to read an ICS calendar and upload new events to
  Nightscout.

  Pre-Requisites:
    pip install ics

  Usage:
    python calendar_import.py <path-to-file-or-url> <days-to-look-back>

  Example:
    FILTER="Keyword,Sensitive" NIGHTSCOUT_URL=https://example.url.com \
      NIGHTSCOUT_SECRET=secret python calendar_import.py example.ics 14

  Environment:
    NIGHTSCOUT_URL
    NIGHTSCOUT_SECRET
    FILTER (List of keywords to filter out entries)
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

from datetime import date, timedelta, datetime
import ics
import nightscout_uploader
import os
import requests
import sys


def main(args):
  if len(args) == 0:
    print USAGE
    sys.exit(1)
  url = args[0]
  if len(args) == 2:
    days = int(args[1])
  else:
    days = 1
  end = date.today()
  start = end  - timedelta(days=days)
  print 'Time Range', start, end

  FILTER=os.environ.get('FILTER', '').split(',')

  if url.startswith('http'):
    text = requests.get(url).text
  else:
    text = open(url, 'r').read().decode('utf-8')

  text = text.replace('BEGIN:VALARM\r\nACTION:NONE','BEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:')
  c = ics.Calendar(text)
  print 'Number of events', len(c.events)
  alldata = []
  for ev in c.events:
      data = []
      print ev.begin, ev.end, ev.all_day, ev.name, ev.uid
      if any((f in ev.name) for f in FILTER):
        print '  Skip, filtered'
        continue
      s = ev.begin.datetime
      while s.date() <= end and s.date() <= ev.end.date():
        if s.date() >= start:
          value = {'notes': 'Kalendar: %s' % (ev.name), 'id': ev.uid}
          if ev.duration.days == 0:
            value.update({'duration': ev.duration.seconds / 60})
          if ev.all_day:
            data.append((s + timedelta(hours=12), value))
          else:
            data.append((s, value))
        s += timedelta(days=1)
      if data:
        print '  ', data
        alldata.extend(data)

  if alldata:
    print len(alldata), 'Entries to upload'
    uploader = nightscout_uploader.NightscoutUploader(device='calendar_import_py')
    response = uploader.upload_notes(alldata)
    print 'Response', response.read()
  else:
    print 'No matching entries found'


main(sys.argv[1:])
