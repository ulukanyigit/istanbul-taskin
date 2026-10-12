// Node için veri yükleyici (tarayıcıdaki yükleyiciyle aynı biçim)
const fs = require("fs"), zlib = require("zlib"), path = require("path");
const TIP = { u1: Uint8Array, u2: Uint16Array, u4: Uint32Array, i4: Int32Array, f4: Float32Array, f8: Float64Array, i2: Int16Array };
function yukle(dizin) {
  const meta = JSON.parse(fs.readFileSync(path.join(dizin, "meta.json"), "utf8"));
  const out = { meta };
  for (const [ad, tablo] of Object.entries(meta.dosya)) {
    const ham = zlib.gunzipSync(fs.readFileSync(path.join(dizin, ad + ".bin")));
    const buf = ham.buffer.slice(ham.byteOffset, ham.byteOffset + ham.byteLength);
    out[ad] = {};
    for (const [k, [o, t, n]] of Object.entries(tablo)) out[ad][k] = new TIP[t](buf, o, n);
  }
  out.tesisler = JSON.parse(fs.readFileSync(path.join(dizin, "tesisler.json"), "utf8"));
  return out;
}
module.exports = { yukle };
