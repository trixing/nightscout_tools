#!/bin/bash
#
# Docker container script to be invoked by cron.
#
# Released under MIT license. See the accompanying LICENSE.txt file for
# full terms and conditions
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
#

if [ "x" == "x$URL" ]; then
  URL="$1"
fi

OUTPUT="$(cd /app/ && ./run_autotune.sh $URL)"

env

echo "$OUTPUT"

curl -s --user "api:$MAILGUN_APIKEY" \
	https://api.mailgun.net/v3/$MAILGUN_DOMAIN/messages \
	-F from="Autotune <autotune@$MAILGUN_DOMAIN>" \
	-F to="$TO" \
	-F subject="Nightscout Autotune Report" \
	-F text="$OUTPUT" \
	--form-string html="<html><pre>$OUTPUT</pre></html>"
