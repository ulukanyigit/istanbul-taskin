/* İstanbul taşkın simülatörü — zaman adımlı kova motoru.
 *
 * pipeline/maruziyet/motor.py'nin tarayıcı karşılığı. Drenaj kapasitesi 0, pompa yok ve tek adımda verilen yağış
 * için sonuç motor.py ile aynıdır (test: web/test/motor_test.js).
 *
 * Her adımda: (1) her çukurun yerel havzasından SCS-CN akışı (birikimli yağıştan), (2) boru patlaması varsa o
 * noktanın havzasındaki çukura su, (3) kademe sırasıyla (memba → mansap) her çukurda drenaj kapasitesi kadar su
 * şebekeye gider, kapasiteyi aşan su alıcı çukura taşar (alıcı yoksa denize/dereye), (4) hipsometriden su seviyesi.
 * Akış süresi ihmal edilir: adım içinde taşan su aynı adımda alıcıya ulaşır.
 */
(function (kok) {
  "use strict";

  function scsQ(P, cn) {
    const S = 25400 / cn - 254;
    if (S <= 0) return P;
    const Pe = Math.max(P - 0.2 * S, 0);
    return (Pe * Pe) / (Pe + S);
  }

  // Yağış deseni: birikimli yağış oranı F(t/D) ∈ [0,1]
  function birikimli(desen, x) {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    if (desen === "duzgun") return x;
    const r = desen === "basta" ? 0.25 : desen === "sonda" ? 0.75 : 0.5; // üçgen hiyetograf, tepe r·D'de
    return x <= r ? (x * x) / r : 1 - ((1 - x) * (1 - x)) / (1 - r);
  }

  class Motor {
    /** d: {meta, model:{...typed arrays}, piksel:{dz}, maruz:{...}} */
    constructor(d) {
      const M = d.model, meta = d.meta;
      this.meta = meta;
      this.m = meta.m;
      this.A = meta.piksel_alan_m2;
      this.cnMin = meta.cn_min;
      this.cnN = meta.cn_n;
      Object.assign(this, {
        ofset: M.ofset, alici: M.alici, kap: M.kap, sira: M.sira, kat: M.kat, ilIci: M.il_ici,
        yerelPx: M.yerel_px, cnPtr: M.cn_ptr, cnKod: M.cn_kod, cnSay: M.cn_say,
      });
      // hipsometri: tabandan yükseklik (m) ve önek toplamları
      const dz = d.piksel.dz, n = dz.length;
      this.dz = new Float32Array(n);
      this.onek = new Float64Array(n + 1);
      for (let i = 0; i < n; i++) {
        const v = dz[i] / 100;
        this.dz[i] = v;
        this.onek[i + 1] = this.onek[i] + v;
      }
      this.altgecit = meta.kategori.indexOf("alt_gecit");
      // ek senaryolar (08_senaryo_paket.py): menfez göletleri m0+1..m, 1990 CN histogramı
      this.m0 = meta.m0 || meta.m;
      this.besOfs = M.m_bes_ofs || null; this.bes = M.m_bes || null;
      this.cn90 = M.cn90_ptr ? { ptr: M.cn90_ptr, kod: M.cn90_kod, say: M.cn90_say } : null;
      this.pasif = new Uint8Array(this.m + 1);
      for (let b = this.m0 + 1; b <= this.m; b++) this.pasif[b] = 1;   // göletler varsayılan kapalı
      this.X = d.maruz;
      let nb = 0;
      for (let i = 0; i < this.X.b_i.length; i++) if (this.X.b_i[i] + 1 > nb) nb = this.X.b_i[i] + 1;
      this.nBina = nb;
      let nt = 0;
      for (let i = 0; i < this.X.t_i.length; i++) if (this.X.t_i[i] + 1 > nt) nt = this.X.t_i[i] + 1;
      this.nTesis = nt;
      this.tesisler = d.tesisler || null;
    }

    /** b çukurunda V m³ su varken su seviyesi (tabandan, m) ve ıslak piksel sayısı. motor.py::_seviyeler ile aynı. */
    seviye(b, V) {
      const o0 = b === 0 ? 0 : this.ofset[b - 1], o1 = this.ofset[b], n = o1 - o0;
      if (n === 0 || V <= 0) return [NaN, 0];
      const v = V / this.A, dz = this.dz, P = this.onek;
      // en küçük k (1..n) öyle ki k·dz[k] − S_k ≥ v  (dz[n] = ∞)
      let lo = 1, hi = n;
      while (lo < hi) {
        const k = (lo + hi) >> 1;
        if (k * dz[o0 + k] - (P[o0 + k] - P[o0]) >= v) hi = k; else lo = k + 1;
      }
      const k = lo;
      return [(v + (P[o0 + k] - P[o0])) / k, k];
    }

    /** Yerel akış (m³) — birikimli yağış Pmm için, çukur başına. q tablosu dışarıdan verilebilir. */
    yerelAkis(Pmm, cikti, cnTablo, pasif) {
      const q = new Float64Array(this.cnN);
      for (let c = 0; c < this.cnN; c++) q[c] = scsQ(Pmm, this.cnMin + c);
      const out = cikti || new Float64Array(this.m + 1), f = this.A / 1000;
      const T = cnTablo || { ptr: this.cnPtr, kod: this.cnKod, say: this.cnSay }, P = pasif || this.pasif;
      const ptr = T.ptr, kod = T.kod, say = T.say;
      for (let b = 0; b <= this.m; b++) {
        if (P[b]) { out[b] = 0; continue; }
        let s = 0;
        for (let j = ptr[b]; j < ptr[b + 1]; j++) s += say[j] * q[kod[j]];
        out[b] = s * f;
      }
      return out;
    }

    /** motor.py::senaryo(P) karşılığı (drenaj yok, tek adım). */
    tekAdim(Pmm) {
      const V = this.yerelAkis(Pmm);
      this._kademe(V, null, null);
      const sev = new Float32Array(this.m + 1), islak = new Uint32Array(this.m + 1);
      for (let b = 1; b <= this.m; b++) {
        const [h, k] = this.seviye(b, Math.min(V[b], this.kap[b]));
        sev[b] = h; islak[b] = k;
        V[b] = Math.min(V[b], this.kap[b]);
      }
      return { hacim: V, seviye: sev, islak };
    }

    /** Kademe: drenaj (varsa) ve taşma. depo yerinde güncellenir; dönüş: [şebekeye giden, denize/dereye giden] m³. */
    _kademe(depo, drenaj, sira, alici) {
      sira = sira || this.sira; alici = alici || this.alici;
      const kap = this.kap;
      let sebeke = 0, disari = 0;
      for (let i = 0; i < sira.length; i++) {
        const b = sira[i];
        let s = depo[b];
        if (drenaj && s > 0) {
          const d = Math.min(s, drenaj[b]);
          s -= d; sebeke += d;
        }
        const fazla = s - kap[b];
        if (fazla > 0) {
          s = kap[b];
          const r = alici[b];
          if (r > 0) depo[r] += fazla; else disari += fazla;
        }
        depo[b] = s;
      }
      return [sebeke, disari];
    }

    /**
     * Zaman adımlı senaryo.
     * p: {P_mm, sure_dk, desen: 'duzgun'|'basta'|'orta'|'sonda', sonra_dk, dt_dk, drenaj_mmsa, pompa (bool),
     *     pompa_m3s, patlama: null | {cukur, debi_m3s, bas_dk, sure_dk}}
     */
    simule(p) {
      const m = this.m, dt = p.dt_dk || 5;
      let seriBir = null;
      if (p.seri && p.seri.length) {                    // birikimli seri: seriBir[s] = s. adım sonuna kadar toplam mm
        seriBir = new Float64Array(p.seri.length + 1);
        for (let i = 0; i < p.seri.length; i++) seriBir[i + 1] = seriBir[i] + p.seri[i];
        p.sure_dk = p.seri.length * dt; p.P_mm = seriBir[p.seri.length];
      }
      const N = Math.ceil((p.sure_dk + (p.sonra_dk || 0)) / dt);
      const seviyeler = new Float32Array((N + 1) * (m + 1));
      const depo = new Float64Array(m + 1), onceki = new Float64Array(m + 1).fill(-1);
      const sev = new Float32Array(m + 1).fill(NaN), islak = new Uint32Array(m + 1);
      const akisOnceki = new Float64Array(m + 1), akis = new Float64Array(m + 1);
      const dolmaDk = new Float32Array(m + 1).fill(NaN), islakDk = new Float32Array(m + 1).fill(NaN);
      const tepe = new Float32Array(m + 1).fill(NaN);
      // drenaj kapasitesi: adım başına m³
      const drenaj = new Float64Array(m + 1);
      const dren = (p.drenaj_mmsa || 0) * (dt / 60) / 1000 * this.A;
      const pompa = p.pompa ? (p.pompa_m3s || 0) * dt * 60 : 0;
      for (let b = 1; b <= m; b++) drenaj[b] = dren * this.yerelPx[b] + (this.kat[b] === this.altgecit ? pompa : 0);
      const drenajVar = dren > 0 || pompa > 0;
      const st = {
        t_dk: new Float32Array(N + 1), yagis_mm: new Float32Array(N + 1), birikimli_mm: new Float32Array(N + 1),
        islak_km2: new Float32Array(N + 1), depo_m3: new Float64Array(N + 1), sebeke_m3: new Float64Array(N + 1),
        disari_m3: new Float64Array(N + 1), bina10: new Uint32Array(N + 1), bina30: new Uint32Array(N + 1),
        nufus10: new Float32Array(N + 1), yol_km: new Float32Array(N + 1), dolu_cukur: new Uint32Array(N + 1),
        tesis: [0, 1, 2, 3].map(() => new Uint16Array(N + 1)),
      };
      const X = this.X, bd = new Float32Array(this.nBina), td = new Float32Array(this.nTesis);
      const pat = p.patlama && p.patlama.cukur > 0 ? p.patlama : null;
      // senaryo: arazi örtüsü ve tıkalı menfezler
      const cnT = p.arazi === "1990" && this.cn90 ? this.cn90 : null;
      const pasif = this.pasif.slice();
      let alici = this.alici, sira = this.sira;
      const acik = (p.menfezler || []).filter((g) => g >= 0 && this.m0 + 1 + g <= this.m);
      if (acik.length && this.besOfs) {
        alici = this.alici.slice();
        for (const g of acik) {
          const id = this.m0 + 1 + g;
          pasif[id] = 0;
          for (let j = this.besOfs[g]; j < this.besOfs[g + 1]; j++) alici[this.bes[j]] = id;
        }
        sira = basamakSirasi(alici);
      }
      let sebekeTop = 0, disariTop = 0;
      for (let s = 0; s <= N; s++) {
        const t = s * dt;
        st.t_dk[s] = t;
        // yağış: ya hazır seri (adım başına mm, geçmiş olaylar) ya da toplam + desen
        let Pk;
        if (seriBir) Pk = seriBir[Math.min(s, seriBir.length - 1)];
        else Pk = p.P_mm * birikimli(p.desen || "orta", p.sure_dk > 0 ? t / p.sure_dk : 1);
        st.birikimli_mm[s] = Pk;
        st.yagis_mm[s] = s === 0 ? 0 : Pk - st.birikimli_mm[s - 1];
        if (s > 0) {
          this.yerelAkis(Pk, akis, cnT, pasif);
          for (let b = 1; b <= m; b++) { depo[b] += akis[b] - akisOnceki[b]; akisOnceki[b] = akis[b]; }
          if (pat) {
            const a0 = pat.bas_dk, a1 = pat.bas_dk + pat.sure_dk;
            const ortak = Math.max(0, Math.min(t, a1) - Math.max(t - dt, a0));
            depo[pat.cukur] += pat.debi_m3s * ortak * 60;
          }
          const [sb, ds] = this._kademe(depo, drenajVar ? drenaj : null, sira, alici);
          sebekeTop += sb; disariTop += ds;
        }
        st.sebeke_m3[s] = sebekeTop; st.disari_m3[s] = disariTop;
        // seviyeler (yalnız değişen çukurlar)
        let islakPx = 0, top = 0, dolu = 0;
        for (let b = 1; b <= m; b++) {
          const V = depo[b];
          if (V !== onceki[b]) {
            const r = this.seviye(b, V);
            sev[b] = r[0]; islak[b] = r[1]; onceki[b] = V;
          }
          top += V;
          if (this.ilIci[b]) islakPx += islak[b];
          if (V >= this.kap[b] * 0.999 && this.kap[b] > 0) {
            dolu++;
            if (isNaN(dolmaDk[b])) dolmaDk[b] = t;
          }
          if (V > 0 && isNaN(islakDk[b])) islakDk[b] = t;
          if (!(sev[b] <= tepe[b])) tepe[b] = sev[b];
        }
        seviyeler.set(sev, s * (m + 1));
        st.islak_km2[s] = (islakPx * this.A) / 1e6;
        st.depo_m3[s] = top;
        st.dolu_cukur[s] = dolu;
        // maruziyet
        this._maruziyet(sev, bd, td);
        let b10 = 0, b30 = 0, nf = 0;
        for (let i = 0; i < bd.length; i++) {
          if (!X.b_ist[i]) continue;
          if (bd[i] >= 0.1) { b10++; nf += X.b_nufus[i]; if (bd[i] >= 0.3) b30++; }
        }
        st.bina10[s] = b10; st.bina30[s] = b30; st.nufus10[s] = nf;
        let yk = 0;
        for (let i = 0; i < X.y_cuk.length; i++) {
          if (X.y_ist[i] && sev[X.y_cuk[i]] - X.y_dz[i] / 100 >= 0.3) yk += X.y_uz[i];
        }
        st.yol_km[s] = yk / 1000;
        this._tesisSay(td, st.tesis, s);
      }
      return { N, dt, m, seviyeler, st, dolmaDk, islakDk, tepe, p };
    }

    /** sev (çukur başına seviye) için bina ve tesis duvarındaki en büyük su derinliği. */
    _maruziyet(sev, bd, td) {
      const X = this.X;
      bd.fill(0); td.fill(0);
      for (let i = 0; i < X.b_i.length; i++) {
        const d = sev[X.b_cuk[i]] - X.b_dz[i] / 100;
        if (d > bd[X.b_i[i]]) bd[X.b_i[i]] = d;
      }
      for (let i = 0; i < X.t_i.length; i++) {
        const d = sev[X.t_cuk[i]] - X.t_dz[i] / 100;
        if (d > td[X.t_i[i]]) td[X.t_i[i]] = d;
      }
    }

    _tesisSay(td, hedef, s) {
      const T = this.tesisler;
      if (!T) return;
      for (let i = 0; i < td.length; i++) {
        if (td[i] >= 0.1 && T[i].ist) hedef[T[i].tur][s]++;
      }
    }
  }

  /** Taşma ağacında memba → mansap işlem sırası (motor.py::_basamak ile aynı, derinlik azalan, kararlı). */
  function basamakSirasi(alici) {
    const m = alici.length - 1, der = new Int32Array(m + 1).fill(-1), yol = new Int32Array(m + 1);
    der[0] = 0;
    for (let b = 1; b <= m; b++) {
      if (der[b] >= 0) continue;
      let k = 0, c = b;
      while (c > 0 && der[c] < 0) { yol[k++] = c; c = alici[c]; }
      let base = c > 0 ? der[c] : 0;
      for (let j = k - 1; j >= 0; j--) der[yol[j]] = ++base;
    }
    const idx = Array.from({ length: m }, (_, i) => i + 1);
    idx.sort((a, b) => der[b] - der[a] || a - b);
    return Uint16Array.from(idx);
  }

  const api = { Motor, scsQ, birikimli, basamakSirasi };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else kok.TaskinMotor = api;
})(typeof self !== "undefined" ? self : this);
