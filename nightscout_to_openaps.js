#!/usr/bin/env node
/*
 * Tool to read nightscout data and output as OpenAps profile
 *
 * Usage: ./nightscout_to_openaps.js https://example.nightscout.site
 *
 */
/*
  Released under MIT license. See the accompanying LICENSE.txt file for
  full terms and conditions

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
  THE SOFTWARE.

*/

const https = require("https");
const hostname = process.argv[2];

function convertBasal(item)
{
    var convertedBasal = {
      "start": item.time + ":00",
      "minutes": Math.round(item.timeAsSeconds / 60),
      "rate": item.value
  };
  return convertedBasal;
}

function convertProfile(profile)
{
     var p = profile.store[profile.defaultProfile];
    var autotuneProfile =
    {
      "min_5m_carbimpact": 3,
      "dia": Number(p.dia),
      "basalprofile": p.basal.map(convertBasal),
      "isfProfile": {
        "sensitivities": [
          {
              "i": 0,
              "start": p.sens[0].time + ":00",
              "sensitivity": Number(p.sens[0].value),
              "offset": 0,
              "x": 0,
              "endOffset": 1440
          }
        ]
      },
      "carb_ratio": Number(p.carbratio[0].value),
      "curve": "ultra-rapid",
      "autosens_max": 2.0,
      "autosens_min": 0.1
  };
  return autotuneProfile;
}


function convertCurrentProfile() {
  const url = hostname + '/api/v1/profile.json';
  https.get(url, res => {
  res.setEncoding("utf8");
  let body = "";
  res.on("data", data => {
    body += data;
  });
  res.on("end", () => {
    body = JSON.parse(body);
    profile = convertProfile(body[0]);
    var json_profile = JSON.stringify(profile, null, 2);
    console.log(json_profile);
  });
});
}

convertCurrentProfile();

