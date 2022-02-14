from flask import Flask
from flask import render_template
from flask import request
from flask import url_for

import nightscout_to_json
import json
import os
import re

app = Flask(__name__)


@app.route("/")
def index():
    p = {
        'stats_url': url_for('stats', url='URL')
    }
    return render_template('index.html', **p)


@app.route("/<url>/stats.json")
def stats(url):
    start = request.args.get('start', None)
    end = request.args.get('end', None)
    try:
        days = int(request.args.get('days', 7))
    except ValueError:
        return '<p>Error, days need to be positive integers</p>'
    raw = bool(request.args.get('raw', False))
    if not days or days < 1 or days > 90:
        return '<p>Error, need positive days, and at maximum 90</p>'
    if not re.match(r'^[0-9a-z\-.]+$', url):
        return '<p>Error, URL malformed, no http or https, https is preprepended automatically</p>'
    url = 'https://' + url
    print(url, start, end, days)
    resp = ""
    ret, new, log = nightscout_to_json.run(url, start=start, end=end, days=days, cache=False)
    data = nightscout_to_json.stats(new)
    if raw:
        data['raw'] = new
    return app.response_class(
        response=json.dumps(data, indent=4),
        status=200,
        mimetype='application/json'
    )


if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_ENV', 'development') == 'development', host='0.0.0.0')
