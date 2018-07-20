#!/bin/sh

OUTPUT="$(cd /app/ && ./run_autotune.sh $URL)"

echo "$OUTPUT"

curl -s --user "api:$MAILGUN_APIKEY" \
	https://api.mailgun.net/v3/$MAILGUN_DOMAIN/messages \
	-F from="Autotune <autotune@$MAILGUN_DOMAIN>" \
	-F to="$TO" \
	-F subject="Nightscout Autotune Report" \
	-F text="$OUTPUT" \
	--form-string html="<html><pre>$OUTPUT</pre></html>"
