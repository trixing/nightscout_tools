FROM node:slim

MAINTAINER Jan Dittmer <jdi@l4x.org>

RUN npm install oref0

RUN apt-get update && apt-get -y install jq cron

RUN for ext in sh py js; do for f in  /node_modules/oref0/bin/*.$ext; do ln -s $f /usr/local/bin/$(basename "$f" .$ext); done; done

RUN mkdir /app

ENV URL=https://example.night.scout
ENV MAILGUN_APIKEY=7a0c3ca9709463d8737eaae438ed574b-8889127d-31644a08
ENV MAILGUN_DOMAIN=sys.trixing.net
ENV TO=jdi@l4x.org

COPY *.js *.sh /app/

WORKDIR /app

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["cron", "-f", "-l", "15"]
