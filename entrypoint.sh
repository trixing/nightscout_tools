#!/bin/bash

ENV="URL=$URL MAILGUN_APIKEY=$MAILGUN_APIKEY MAILGUN_DOMAIN=$MAILGUN_DOMAIN TO=$TO "

echo "0 5 * * * $ENV /app/run.sh $URL >/proc/1/fd/1 2>/proc/1/fd/2" | crontab -

exec "$@"
