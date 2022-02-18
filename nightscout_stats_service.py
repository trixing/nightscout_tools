from flask import Flask
from flask import render_template
from flask import request
from flask import url_for

import nightscout_to_json
import json
import os
import re
import datetime
import html


app = Flask(__name__)

DEBUG = (os.getenv('FLASK_ENV', 'development') == 'development')
CACHE = {}

@app.route("/")
def index():
    p = {
        'stats_url': url_for('stats', url='URL'),
        'all_url': url_for('all_data', url='URL')
    }
    return render_template('index.html', **p)



def get_data(url, request):
    start = request.args.get('start', None)
    end = request.args.get('end', None)
    try:
        days = int(request.args.get('days', 7))
    except ValueError:
        return '<p>Error, days need to be positive integers</p>'
    raw = bool(request.args.get('raw', False))

    if not days or days < 1 or days > 90:
        return '<p>Error, need positive days, and at maximum 90</p>'

    url = url.lower()
    if not re.match(r'^[0-9a-z\-.]+$', url):
        return '<p>Error, URL malformed, no http or https, https:// is preprepended automatically</p>'

    cache_key = (url, start, end, days, raw)
    cache_contents = CACHE.get(cache_key, None)
    data = None
    if cache_contents:
        data = cache_contents['data']
        new = cache_contents['raw']
        delta = datetime.datetime.now() - cache_contents['date']
        print('Delta', delta)
        if delta > datetime.timedelta(hours=1):
            print('Cache too old')
            data = None
        else:
            print('Using cached content')

    if not data:
        url = 'https://' + url
        resp = ""
        try:
            ret, new, log = nightscout_to_json.run(url, start=start, end=end, days=days, cache=False)
        except Exception as e:
            print(e)
            if DEBUG or request.args.get('debug', 0):
                raise e
            else:
                return '<p>Error getting data from host %s: %s</p>' % (url, html.escape(str(e)))
        for l in log:
            print('  Debug: ', l)
        data = nightscout_to_json.stats(new)
        CACHE[cache_key] = {'date': datetime.datetime.now(), 'data': data, 'raw': new}

    return data, new


@app.route("/<url>/stats.json")
def stats(url):
    ret = get_data(url, request)
    if type(ret) == str:
        return ret
    data, new = ret
    return app.response_class(
        response=json.dumps(data, indent=4),
        status=200,
        mimetype='application/json'
    )


@app.route("/<url>/all.json")
def all_data(url):
    ret = get_data(url, request)
    if type(ret) == str:
        return ret
    data, new = ret
    data['all'] = new
    return app.response_class(
        response=json.dumps(data, indent=4),
        status=200,
        mimetype='application/json'
    )


if __name__ == '__main__':
    app.run(debug=DEBUG, host='0.0.0.0')
