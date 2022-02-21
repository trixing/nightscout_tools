from flask import Flask
from flask import render_template
from flask import request
from flask import url_for


from flask import has_request_context, request
from flask.logging import default_handler
import logging


class RequestFormatter(logging.Formatter):
    def format(self, record):
        if has_request_context():
            record.url = request.url
            record.remote_addr = request.remote_addr
        else:
            record.url = None
            record.remote_addr = None

        print(record)

        msg = super().format(record)
        msg = re.sub(r'token=[^&]+', 'token=<private>', msg)
        return msg


formatter = RequestFormatter(
    '%(message)s'
    #'[%(asctime)s] %(remote_addr)s requested %(url)s\n'
    #'%(levelname)s in %(module)s: %(message)s'
)
default_handler.setFormatter(formatter)
root = logging.getLogger()
root.addHandler(default_handler)


import json
import os
import re
import datetime
import html

import nightscout_to_json


DEBUG = (os.getenv('FLASK_ENV', 'development') == 'development')
CACHE = {}


app = Flask(__name__)
app.logger.addHandler(default_handler)


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
    token = request.args.get('token', None)
    api_secret = request.headers.get('api-secret', None)
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
            ret, new, log = nightscout_to_json.run(url, start=start, end=end, days=days, cache=False,
                                                   token=token, hashed_secret=api_secret)
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
