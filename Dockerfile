# docker build -t trixing/autotune .
# docker tag trixing/autotune:latest registry.trixing.net/trixing/autotune:live
FROM node:slim

MAINTAINER Jan Dittmer <jdi@l4x.org>

RUN apt-get update && apt-get -y install jq cron git bc locales && apt-get clean
RUN localedef -i en_US -c -f UTF-8 -A /usr/share/locale/locale.alias en_US.UTF-8

RUN npm install trixing/oref0\#v0.7.0-dev-trixing1

RUN for ext in sh py js; do for f in  /node_modules/oref0/bin/*.$ext; do ln -s $f /usr/local/bin/$(basename "$f" .$ext); ln -s $f /usr/local/bin/$(basename "$f"); done; done

ENV TZ=Europe/Berlin
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN mkdir /app

ENV URL=https://example.night.scout
ENV MAILGUN_APIKEY=mailgun-api-key
ENV MAILGUN_DOMAIN=example.com
ENV TO=mail@example.com
ENV CRON="0 5 * * *"

COPY *.js *.sh /app/

WORKDIR /app

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["cron", "-f", "-l", "15"]
