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


class InvalidAPIUsage(Exception):

            def __init__(self, message, status_code=500, payload=None):
                        super().__init__()
                        self.message = message
                        self.status_code = status_code
                        self.payload = payload


@app.errorhandler(500)
def invalid_api_usage(e):
        return '<p>' + str(e) + '</p>', 500


@app.errorhandler(InvalidAPIUsage)
def invalid_api_usage_exception(e):
        return render_template('error.html',
                               message=e.message,
                               status_code=e.status_code,
                               request_url=html.escape(request.url)
                              ), e.status_code


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
        raise InvalidAPIUsage('days needs to be a positive integer.')
    raw = bool(request.args.get('raw', False))

    if not days or days < 1 or days > 90:
        raise InvalidAPIUsage('days need to be positive and smaller than 90.')

    url = url.lower()
    if not re.match(r'^[0-9a-z\-.]+$', url):
        raise InvalidAPIUsage('URL malformed, no http or https needed, https:// is preprepended automatically.')

    cache_key = (url, start, end, days, raw)
    cache_contents = CACHE.get(cache_key, None)
    data = None
    if cache_contents:
        data = cache_contents['data']
        new = cache_contents['raw']
        delta = datetime.datetime.now() - cache_contents['date']
        if delta > datetime.timedelta(hours=1):
            logging.info('Cache too old: %s', delta)
            data = None
        else:
            logging.info('Using cached content from %s', cache_contents['date'])
            data['cached'] = True

    if not data:
        url = 'https://' + url
        resp = ""
        try:
            ret, new, log = nightscout_to_json.run(url, start=start, end=end, days=days, cache=False,
                                                   token=token, hashed_secret=api_secret)
        except nightscout_to_json.DownloadError as e:
            logging.warning('Failed to contact upstream %s: %s' % (url, str(e)))
            raise InvalidAPIUsage('failed to get data from Nightscout instance: ' + e.args[1], 504)
        except Exception as e:
            logging.warning('Error of type %s: %s' % (type(e), e))
            logging.exception(e)
            if DEBUG or request.args.get('debug', 0):
                raise e
            else:
                raise InvalidAPIUsage('failed to process data from Nightscount instance.', 504)
        for l in log:
            logging.info('  Debug: ', l)
        data = nightscout_to_json.stats(new)
        data['url'] = url
        data['generated'] = datetime.datetime.now().isoformat()
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


@app.route("/<url>/marc.json")
def marc(url):
    ret = get_data(url, request)
    if type(ret) == str:
        return ret
    data, new = ret
    daily = data['overall']['daily_average']
    data = {
        'tdd': daily['insulin'],
        'basal': daily['prog_basal'],
        'carbs': daily['carbs'],
        'url': data['url'],
        'generated': data['generated']
    }
    return app.response_class(
        response=json.dumps(data, indent=4),
        status=200,
        mimetype='application/json'
    )


@app.route("/<url>/<part>.csv")
def daily_csv(url, part):
    ret = get_data(url, request)
    if type(ret) == str:
        return ret
    data, new = ret
    s = []
    if part == 'daily_average':
        for k, v in data['overall']['daily_average'].items():
            s.append('"%s",%.1f' % (k, v))
    else:
        abort(404)
    return app.response_class(
        response='\n'.join(s),
        status=200,
        mimetype='text/plain'
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
