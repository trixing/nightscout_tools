# Trixing Nightscout Tools

Various tools to interact with Nightscout data.

## run_autotune.sh

This tool will use data from a Nightscout website, convert
it to a profile understood by OpenAps, and run autotune
on it.

Customization is available in the code.

To use:

$ ./run_autotune.sh https://example.nightscout.site

## Docker

$ docker build -t trixing/autotune .

You may want to customize a few environment variables, the most important
one being the URL.  Their is a few more mailing related things in the
Dockerfile if you want to see the results not only in the docker logs.

$ docker run -e URL=https://example.com trixing/autotune
