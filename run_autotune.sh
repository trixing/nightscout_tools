#!/bin/sh
#
# Tool to run OpenAPS oref0 Autotune on Nightscout data iteratively
# for multiple history ranges and output the result.
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
set -e

NIGHTSCOUT="$1"
OUTPUT="$PWD/runfiles"

test -d "$OUTPUT" || mkdir "$OUTPUT"

PATH="/node_modules/oref0/bin/:/usr/local/bin:$PATH"

for DAYS in 1 8 15; do
   START=`date -d "-$DAYS days" +"%Y-%m-%d"`
   END=`date -d "-1 days" +"%Y-%m-%d"`

   echo "-- $START - $END --"

   BASE="$OUTPUT/$DAYS"
   test -d "$BASE" && rm -rf "$BASE"
   DST="$BASE/settings"
   TARGET="$BASE/autotune"
   test -d "$DST" || mkdir -p "$DST"
   test -d "$TARGET" || mkdir -p "$TARGET"
   node nightscout_to_openaps.js "$NIGHTSCOUT" > "$DST/profile.json"
   cp "$DST/profile.json" "$DST/pumpprofile.json"
   cp "$DST/profile.json" "$DST/autotune.json"
   for i in `seq 1`; do
	echo "-------- Iteration $i --------"
	if oref0-autotune --dir="$BASE" --ns-host=$NIGHTSCOUT --start-date=$START --end-date=$END > "$TARGET/$i.log" 2>&1; then
		cp "$TARGET/profile.json" "$DST/pumpprofile.json"
		cat "$TARGET/autotune_recommendations.log"
	else
		cat "$TARGET/$i.log"
		exit 3
	fi
   done
   echo
   echo
done
