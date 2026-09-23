// Format ribuan saat mengetik (11000000 -> 11.000.000). Server menerima keduanya.
function fmtMoney(el){
  const d = el.value.replace(/[^\d]/g,'');
  el.value = d ? Number(d).toLocaleString('id-ID') : '';
}
document.addEventListener('input', e => { if (e.target.classList.contains('money')) fmtMoney(e.target); });
document.querySelectorAll('input.money').forEach(fmtMoney);

// Bottom sheet
function openSheet(id, data){
  const dlg = document.getElementById(id); if (!dlg) return;
  if (data) for (const [k,v] of Object.entries(data)) {
    const f = dlg.querySelector(`[name="${k}"]`);
    if (!f) continue;
    if (f.type === 'checkbox') f.checked = !!v; else if (f.tomselect) f.tomselect.setValue(v ?? '', true); else f.value = v ?? '';
    if (f.classList.contains('money')) fmtMoney(f);
  }
  if (window.syncPickers) window.syncPickers(dlg);
  dlg.showModal();
  const first = dlg.querySelector('input.money, input:not([type=hidden])');
  if (first && window.matchMedia('(min-width:720px)').matches) setTimeout(() => first.focus(), 60);
}
function closeSheet(dlg){
  if (!dlg || !dlg.open || dlg.classList.contains('closing')) return;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduced) { dlg.close(); return; }
  dlg.classList.add('closing');
  const panel = dlg.querySelector('.panel');
  const done = () => { dlg.classList.remove('closing'); dlg.close(); };
  panel.addEventListener('animationend', done, { once: true });
  setTimeout(done, 400);   // jaga-jaga bila animationend tidak terpanggil
}
document.addEventListener('click', e => {
  const o = e.target.closest('[data-open]'); if (o) { openSheet(o.dataset.open, o.dataset.fill ? JSON.parse(o.dataset.fill) : null); return; }
  const c = e.target.closest('[data-close]'); if (c) { closeSheet(c.closest('dialog')); return; }
  const dlg = e.target.closest('dialog.sheet');
  if (dlg && e.target === dlg) closeSheet(dlg);   // tap di luar panel
});
// Esc -> animasi tutup juga
document.addEventListener('cancel', e => { if (e.target.matches('dialog.sheet')) { e.preventDefault(); closeSheet(e.target); } }, true);
// Geser panel ke bawah untuk menutup (ponsel)
document.querySelectorAll('dialog.sheet .panel').forEach(panel => {
  let y0 = null;
  panel.addEventListener('touchstart', e => { if (panel.scrollTop === 0) y0 = e.touches[0].clientY; }, { passive: true });
  panel.addEventListener('touchmove', e => {
    if (y0 === null) return; const dy = e.touches[0].clientY - y0;
    if (dy > 0) panel.style.transform = `translateY(${dy * 0.6}px)`;
  }, { passive: true });
  panel.addEventListener('touchend', e => {
    if (y0 === null) return; const dy = e.changedTouches[0].clientY - y0; y0 = null;
    panel.style.transition = 'transform .25s cubic-bezier(.2,.8,.2,1)'; panel.style.transform = '';
    setTimeout(() => panel.style.transition = '', 260);
    if (dy > 90) closeSheet(panel.closest('dialog'));
  });
});
// Baris transaksi -> edit
document.addEventListener('click', e => {
  const r = e.target.closest('.row[data-edit]'); if (!r || e.target.closest('form,button,a')) return;
  const dlg = document.getElementById('sheet-edit');
  const d = JSON.parse(r.dataset.edit);
  // isi kategori sesuai jenis transaksi sebelum nilai di-set
  const sel = dlg.querySelector('#edit-category');
  const ids = window.CATS[d.kind] || [], names = window.CATS[d.kind + 'Names'] || [];
  if (sel.tomselect) {
    const ts = sel.tomselect; ts.clear(true); ts.clearOptions();
    ts.addOption({ value: '', text: '—' });
    ids.forEach((id, i) => ts.addOption({ value: String(id), text: names[i] }));
    ts.refreshOptions(false);
  } else {
    sel.innerHTML = '<option value="">—</option>' + ids.map((id, i) => `<option value="${id}">${names[i]}</option>`).join('');
  }
  openSheet('sheet-edit', d);
  dlg.querySelector('form').action = `/tx/${d.id}/edit`;
  const df = dlg.querySelector('[data-del]'); df.action = `/tx/${d.id}/delete`; delete df.dataset.ok;
  df.dataset.confirmWhat = d.description || r.querySelector('.name').textContent; df.dataset.confirmSub = r.querySelector('.amt').textContent + (d.tx_date ? ' · ' + d.tx_date : '');
  const isT = d.kind === 'transfer';
  dlg.querySelector('h3').textContent = isT ? 'Edit transfer' : (d.kind === 'income' ? 'Edit pemasukan' : 'Edit pengeluaran');
  dlg.querySelector('#edit-status-wrap').hidden = d.kind !== 'expense';
  dlg.querySelector('#edit-category-wrap').hidden = isT;
  dlg.querySelector('#edit-to-wrap').hidden = !isT;
  dlg.querySelector('#edit-account-wrap label').textContent = isT ? 'Dari kantong' : 'Kantong';
});
// ===== Popup konfirmasi (pengganti confirm() bawaan) =====
// confirmDialog({title, what, sub, note}) -> Promise<boolean>
window.confirmDialog = function(opt){
  const dlg = document.getElementById('confirm');
  if (!dlg || !dlg.showModal) return Promise.resolve(confirm(opt.title || 'Hapus?'));
  dlg.querySelector('#confirm-title').textContent = opt.title || 'Hapus entri ini?';
  const what = dlg.querySelector('#confirm-what');
  what.hidden = !opt.what; what.querySelector('b').textContent = opt.what || ''; what.querySelector('span').textContent = opt.sub || '';
  const note = dlg.querySelector('#confirm-note'); note.hidden = !opt.note; note.textContent = opt.note || '';
  dlg.querySelector('[data-confirm-yes]').textContent = opt.yes || 'Hapus';
  return new Promise(res => {
    const yes = dlg.querySelector('[data-confirm-yes]'), no = dlg.querySelector('[data-confirm-no]');
    function finish(v){
      yes.onclick = no.onclick = dlg.oncancel = dlg.onclick = null;
      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (reduced) { dlg.close(); res(v); return; }
      dlg.classList.add('closing');
      const done = () => { dlg.classList.remove('closing'); dlg.close(); res(v); };
      dlg.querySelector('.cbox').addEventListener('animationend', done, { once: true });
      setTimeout(done, 300);
    }
    yes.onclick = () => finish(true); no.onclick = () => finish(false);
    dlg.oncancel = e => { e.preventDefault(); finish(false); };
    dlg.onclick = e => { if (e.target === dlg) finish(false); };
    dlg.showModal();
    if (navigator.vibrate) navigator.vibrate(8);
    setTimeout(() => no.focus(), 50);
  });
};
// form[data-confirm] -> tanya dulu lewat popup, lalu kirim
document.addEventListener('submit', e => {
  const f = e.target; if (!f.matches('[data-confirm]') || f.dataset.ok) return;
  e.preventDefault();
  confirmDialog({ title: f.dataset.confirm, note: f.dataset.confirmNote, what: f.dataset.confirmWhat, sub: f.dataset.confirmSub, yes: f.dataset.confirmYes })
    .then(ok => { if (ok) { f.dataset.ok = '1'; f.submit(); } });
});

// ===== Geser kiri pada baris untuk hapus =====
(function(){
  const W = 88, FULL = 0.5;                       // lebar tombol; rasio geser untuk langsung konfirmasi
  let openEl = null;
  function setX(el, x){ el.style.setProperty('--x', x + 'px'); }
  function closeOpen(){ if (openEl) { openEl.classList.add('snap'); setX(openEl, 0); openEl.classList.remove('open', 'arm'); openEl = null; } }
  function ask(el){
    closeOpen(); el.classList.add('snap'); setX(el, W); el.classList.add('open'); openEl = el;
    confirmDialog({ title: 'Hapus entri ini?', what: el.dataset.delTitle, sub: el.dataset.delSub, note: el.dataset.delNote }).then(ok => {
      if (!ok) { closeOpen(); return; }
      const f = document.getElementById('swform'); if (!f) return;
      f.action = el.dataset.del;
      el.style.height = el.offsetHeight + 'px'; el.classList.add('leaving');
      el.addEventListener('animationend', () => f.submit(), { once: true });
      setTimeout(() => f.submit(), 400);
    });
  }
  document.addEventListener('click', e => {
    const b = e.target.closest('.sw-del'); if (b) { ask(b.closest('.sw')); return; }
    if (openEl && !e.target.closest('.sw.open')) closeOpen();
  });
  document.querySelectorAll('.sw').forEach(el => {
    let x0 = 0, y0 = 0, x = 0, base = 0, drag = null, id = null;
    el.addEventListener('pointerdown', e => {
      if (e.button) return;
      x0 = e.clientX; y0 = e.clientY; base = el.classList.contains('open') ? W : 0; drag = null; id = e.pointerId;
      el.classList.remove('snap');
    });
    el.addEventListener('pointermove', e => {
      if (id !== e.pointerId) return;
      const dx = e.clientX - x0, dy = e.clientY - y0;
      if (drag === null) { if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return; drag = Math.abs(dx) > Math.abs(dy) * 1.2; if (!drag) { id = null; return; } el.setPointerCapture(id); if (openEl && openEl !== el) closeOpen(); }
      x = Math.max(0, base - dx);
      const max = el.offsetWidth * FULL;
      if (x > W) x = W + (x - W) * 0.55;             // tahanan setelah tombol terlihat
      setX(el, x);
      const arm = x > max; if (arm !== el.classList.contains('arm')) { el.classList.toggle('arm', arm); if (arm && navigator.vibrate) navigator.vibrate(6); }
      e.preventDefault();
    });
    function end(e){
      if (id !== e.pointerId) return; id = null;
      if (!drag) return;
      el.classList.add('snap');
      const wasArm = el.classList.contains('arm'); el.classList.remove('arm');
      if (wasArm) { ask(el); }
      else if (x > W * 0.45) { setX(el, W); el.classList.add('open'); openEl = el; }
      else { setX(el, 0); el.classList.remove('open'); if (openEl === el) openEl = null; }
      // cegah klik (buka edit) & geser tab setelah drag
      const stop = ev => { ev.stopPropagation(); ev.preventDefault(); };
      el.addEventListener('click', stop, { capture: true, once: true }); setTimeout(() => el.removeEventListener('click', stop, { capture: true }), 350);
      e.stopPropagation();
    }
    el.addEventListener('pointerup', end); el.addEventListener('pointercancel', end);
    el.addEventListener('touchend', e => { if (drag || el.classList.contains('open')) e.stopPropagation(); }, true);
    el.addEventListener('dragstart', e => e.preventDefault());
  });
})();
// Pilih bulan
document.addEventListener('change', e => { if (e.target.id === 'month-select') location.href = '/m/' + e.target.value; });

// Tema terang/gelap: simpan pilihan, default ikut sistem.
(function(){
  const btn = document.getElementById('theme-toggle'); if (!btn) return;
  btn.addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme');
    const sys = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    const now = (cur || sys) === 'dark' ? 'light' : 'dark';
    document.documentElement.classList.add('theming');
    document.documentElement.setAttribute('data-theme', now);
    setTimeout(() => document.documentElement.classList.remove('theming'), 350);
    try { localStorage.setItem('monetary-theme', now); } catch (e) {}
  });
})();

// Dropdown dengan pencarian (Tom Select) untuk semua <select> di form, kecuali yang diberi data-plain.
(function(){
  if (!window.TomSelect) return;
  const isMobile = window.matchMedia('(max-width: 719px)').matches;
  document.querySelectorAll('select:not([data-plain])').forEach(el => {
    if (el.tomselect) return;
    new TomSelect(el, {
      create: false, allowEmptyOption: true, maxOptions: 200,
      plugins: isMobile ? ['dropdown_input'] : [],     // di ponsel, kotak cari di dalam dropdown agar keyboard tidak menutup pilihan
      render: { no_results: () => '<div class="no-results">Tidak ada hasil</div>' },
      onInitialize(){ this.wrapper.classList.add('num'); }
    });
  });
})();

// Setelah simpan (redirect membawa #expense/#income/#ef), beri denyut kecil pada angka yang berubah.
(function(){
  if (!location.hash) return;
  requestAnimationFrame(() => document.querySelectorAll('.grid .v').forEach((el, i) => setTimeout(() => el.classList.add('tick'), 350 + i * 40)));
})();

// ===== Halaman bulan v2 =====
// Tab transaksi: indikator geser, ingat tab terakhir; #expense/#income/#ef membuka tab terkait.
(function(){
  const tabs = document.getElementById('tabs'); if (!tabs) return;
  const btns = [...tabs.querySelectorAll('[data-tab]')];
  const panels = [...document.querySelectorAll('.tpanel')];
  function show(name, save){
    const i = Math.max(0, btns.findIndex(b => b.dataset.tab === name));
    btns.forEach((b, j) => { b.classList.toggle('on', i === j); b.setAttribute('aria-selected', i === j); });
    panels.forEach(p => { const on = p.dataset.panel === btns[i].dataset.tab; if (on !== p.classList.contains('on')) { p.classList.toggle('on', on); } });
    tabs.style.setProperty('--x', i);
    if (save) { try { localStorage.setItem('monetary-tab', btns[i].dataset.tab); } catch (e) {} }
  }
  btns.forEach(b => b.addEventListener('click', () => show(b.dataset.tab, true)));
  const hashMap = { '#expense': 'expense', '#income': 'income', '#ef': 'fund', '#fund': 'fund' };
  let initial = hashMap[location.hash];
  if (!initial) { try { initial = localStorage.getItem('monetary-tab'); } catch (e) {} }
  show(initial || 'expense', false);
  if (location.hash && hashMap[location.hash]) history.replaceState(null, '', location.pathname);
  // geser kiri/kanan di area panel untuk pindah tab (ponsel)
  const wrap = document.querySelector('.panel-wrap'); let x0 = null, y0 = null;
  wrap.addEventListener('touchstart', e => { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
  wrap.addEventListener('touchend', e => {
    if (x0 === null) return; const dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0; x0 = null;
    if (Math.abs(dx) < 60 || Math.abs(dy) > 40) return;
    const i = btns.findIndex(b => b.classList.contains('on')); const n = Math.min(btns.length - 1, Math.max(0, i + (dx < 0 ? 1 : -1)));
    if (n !== i) show(btns[n].dataset.tab, true);
  });
})();

// Strip bulan: bulan aktif selalu terlihat di tengah.
(function(){
  const on = document.querySelector('.mstrip .chip.on'); if (!on) return;
  const strip = on.parentElement;
  const left = on.offsetLeft - (strip.clientWidth - on.offsetWidth) / 2;
  strip.scrollTo({ left, behavior: 'instant' in strip ? 'instant' : 'auto' });
})();

// Angka count-up saat halaman terbuka (hormati prefers-reduced-motion).
(function(){
  const els = document.querySelectorAll('[data-count]'); if (!els.length) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const fmt = n => { const s = Math.abs(Math.round(n)).toLocaleString('id-ID'); return (n < 0 ? '-' : '') + 'Rp ' + s; };
  els.forEach((el, k) => {
    const target = Number(el.dataset.count); if (!isFinite(target)) return;
    const dur = 700, t0 = performance.now() + 120 + k * 60;
    function step(now){
      const p = Math.min(1, Math.max(0, (now - t0) / dur)); const e = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(target * e);
      if (p < 1) requestAnimationFrame(step); else el.textContent = fmt(target);
    }
    el.textContent = fmt(0); requestAnimationFrame(step);
  });
})();

// ===== Picker tanggal & bulan bertema (mengganti input date/month bawaan) =====
(function(){
  const M = ['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des'];
  const ML = ['Januari','Februari','Maret','April','Mei','Juni','Juli','Agustus','September','Oktober','November','Desember'];
  const D = ['Sen','Sel','Rab','Kam','Jum','Sab','Min'];
  const pad = n => String(n).padStart(2, '0');
  const today = new Date(); const todayKey = `${today.getFullYear()}-${pad(today.getMonth()+1)}-${pad(today.getDate())}`;
  function label(kind, v){
    if (!v) return kind === 'month' ? 'Pilih bulan' : 'Pilih tanggal';
    const [y, m, d] = v.split('-').map(Number);
    return kind === 'month' ? `${M[m-1]} ${y}` : `${d} ${M[m-1]} ${y}`;
  }
  let open = null;
  function close(){ if (open) { open.pop.remove(); open = null; document.removeEventListener('pointerdown', onDoc, true); } }
  function onDoc(e){ if (open && !open.pop.contains(e.target) && e.target !== open.btn) close(); }

  function build(input, btn){
    const kind = input.dataset.kind;
    const pop = document.createElement('div'); pop.className = 'dp'; pop.setAttribute('role', 'dialog');
    let view = input.value ? input.value.slice(0, 7) : todayKey.slice(0, 7);
    let [vy, vm] = view.split('-').map(Number);
    if (kind === 'month') vm = 0;
    function set(v){ input.value = v; btn.querySelector('span').textContent = label(kind, v); btn.classList.toggle('empty', !v); input.dispatchEvent(new Event('change', { bubbles: true })); close(); }
    function render(){
      const cur = input.value;
      let h = `<div class="dp-h"><button type="button" class="dp-nav" data-go="-1" aria-label="Sebelumnya">‹</button><b>${kind === 'month' ? vy : ML[vm-1] + ' ' + vy}</b><button type="button" class="dp-nav" data-go="1" aria-label="Berikutnya">›</button></div>`;
      if (kind === 'month') {
        h += '<div class="dp-grid m">' + M.map((n, i) => { const v = `${vy}-${pad(i+1)}`; return `<button type="button" data-v="${v}" class="${v === cur ? 'on' : ''} ${v === todayKey.slice(0,7) ? 'today' : ''}">${n}</button>`; }).join('') + '</div>';
      } else {
        h += '<div class="dp-grid w">' + D.map(d => `<i>${d}</i>`).join('') + '</div><div class="dp-grid d">';
        const first = new Date(vy, vm - 1, 1); const off = (first.getDay() + 6) % 7; const days = new Date(vy, vm, 0).getDate();
        for (let i = 0; i < off; i++) h += '<s></s>';
        for (let d = 1; d <= days; d++) { const v = `${vy}-${pad(vm)}-${pad(d)}`; h += `<button type="button" data-v="${v}" class="${v === cur ? 'on' : ''} ${v === todayKey ? 'today' : ''}">${d}</button>`; }
        h += '</div>';
      }
      h += `<div class="dp-f"><button type="button" class="dp-x" data-clear>Kosongkan</button><button type="button" class="dp-x" data-today>${kind === 'month' ? 'Bulan ini' : 'Hari ini'}</button></div>`;
      pop.innerHTML = h;
    }
    pop.addEventListener('click', e => {
      const go = e.target.closest('[data-go]'); if (go) { const n = +go.dataset.go; if (kind === 'month') vy += n; else { vm += n; if (vm < 1) { vm = 12; vy--; } if (vm > 12) { vm = 1; vy++; } } render(); return; }
      const v = e.target.closest('[data-v]'); if (v) { set(v.dataset.v); return; }
      if (e.target.closest('[data-clear]')) { set(''); return; }
      if (e.target.closest('[data-today]')) { set(kind === 'month' ? todayKey.slice(0, 7) : todayKey); return; }
    });
    render();
    return pop;
  }
  function place(pop, btn){
    const r = btn.getBoundingClientRect(); const w = Math.min(320, window.innerWidth - 24);
    pop.style.width = w + 'px';
    let left = Math.min(Math.max(12, r.left), window.innerWidth - w - 12);
    let top = r.bottom + 6; const hgt = pop.offsetHeight || 320;
    if (top + hgt > window.innerHeight - 12) top = Math.max(12, r.top - hgt - 6);
    pop.style.left = left + 'px'; pop.style.top = top + 'px';
  }
  function upgrade(input){
    if (input.dataset.picker) return;
    const kind = input.type === 'month' ? 'month' : 'date';
    input.dataset.picker = '1'; input.dataset.kind = kind; input.type = 'hidden';
    const btn = document.createElement('button'); btn.type = 'button'; btn.className = 'pick' + (input.value ? '' : ' empty');
    btn.innerHTML = `<span>${label(kind, input.value)}</span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M8 3v4M16 3v4M3 10h18"/></svg>`;
    input.after(btn);
    btn.addEventListener('click', () => {
      if (open && open.btn === btn) { close(); return; } close();
      const pop = build(input, btn);
      (btn.closest('dialog[open]') || document.body).appendChild(pop);
      place(pop, btn); open = { pop, btn };
      setTimeout(() => document.addEventListener('pointerdown', onDoc, true), 0);
    });
    input.addEventListener('sync', () => { btn.querySelector('span').textContent = label(kind, input.value); btn.classList.toggle('empty', !input.value); });
  }
  document.querySelectorAll('input[type=date],input[type=month]').forEach(upgrade);
  window.syncPickers = root => (root || document).querySelectorAll('input[data-picker]').forEach(i => i.dispatchEvent(new Event('sync')));
  document.addEventListener('close', e => { if (e.target.matches('dialog')) close(); }, true);
  window.addEventListener('resize', () => { if (open) place(open.pop, open.btn); });
})();

// ===== Dashboard: pencarian kirim otomatis; chip bulan aktif digulir ke tengah =====
(function(){
  const f = document.getElementById('dash-filters'); if (!f) return;
  let t; f.q.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => f.requestSubmit ? f.requestSubmit() : f.submit(), 550); });
  const on = f.querySelector('.fchips .chip.on'); if (on) { const st = on.parentElement; st.scrollTo({ left: on.offsetLeft - (st.clientWidth - on.offsetWidth) / 2 }); }
})();

// ===== Kolom wajib: tanda * pada label, catatan di footer, dan pesan jelas saat kosong =====
(function(){
  const MSG = { amount: 'Jumlah wajib diisi', password: 'Password wajib diisi', name: 'Nama wajib diisi', symbol: 'Simbol wajib diisi', category: 'Kategori wajib diisi' };
  const label = f => { let el = f.previousElementSibling; while (el && el.tagName !== 'LABEL') el = el.previousElementSibling; if (!el) { const w = f.parentElement; el = w && w.querySelector(':scope > label'); } return el; };
  document.querySelectorAll('form').forEach(form => {
    const req = [...form.querySelectorAll('[required]')]; if (!req.length) return;
    form.noValidate = true;                                   // pakai pesan kita, bukan balon bawaan browser
    req.forEach(f => { const l = label(f); if (l) l.classList.add('req'); });
    const act = form.querySelector('.actions');
    if (act && !act.querySelector('.reqnote') && !form.closest('.doorcard')) act.insertAdjacentHTML('afterbegin', '<small class="reqnote"><b>*</b> wajib diisi</small>');
  });
  function fieldEl(f){ return f.tomselect ? f.tomselect.wrapper : (f.dataset.picker ? f.nextElementSibling : f); }
  function msgFor(f){
    if (f.classList.contains('money')) return (f.value.replace(/\D/g, '') === '' ? MSG.amount : 'Jumlah harus lebih dari 0');
    if (MSG[f.name]) return MSG[f.name];
    const l = label(f); return (l ? l.textContent.replace('*', '').trim() : 'Kolom ini') + ' wajib diisi';
  }
  function invalid(f){
    if (f.disabled) return false;
    if (f.classList.contains('money')) return !(Number(f.value.replace(/\D/g, '')) > 0);
    return f.required && !f.value.trim();
  }
  function clear(f){ const el = fieldEl(f); el.classList.remove('invalid'); const m = el.nextElementSibling; if (m && m.classList.contains('fmsg')) m.remove(); }
  function mark(f){
    clear(f); const el = fieldEl(f); el.classList.add('invalid');
    el.insertAdjacentHTML('afterend', `<div class="fmsg"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg>${msgFor(f)}</div>`);
  }
  document.addEventListener('submit', e => {
    const form = e.target; if (!form.noValidate) return;
    const bad = [...form.querySelectorAll('[required]')].filter(invalid);
    if (!bad.length) return;
    e.preventDefault(); e.stopImmediatePropagation();
    bad.forEach(mark);
    const first = bad[0]; const el = fieldEl(first);
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    if (navigator.vibrate) navigator.vibrate([12, 40, 12]);
    (first.tomselect ? first.tomselect.control_input : (first.dataset.picker ? el : first)).focus({ preventScroll: true });
    const text = bad.length === 1 ? 'Ada kolom wajib (*) yang belum diisi' : `${bad.length} kolom wajib (*) belum diisi`;
    if (form.closest('dialog[open]')) {                       // di dalam sheet: toast tertutup backdrop, pakai banner di atas form
      let b = form.querySelector('.fbanner'); if (!b) { b = document.createElement('div'); b.className = 'fbanner'; form.prepend(b); }
      b.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg><span>${text}</span>`;
      b.hidden = false; b.classList.add('on');
      clearTimeout(b._h); b._h = setTimeout(() => { b.classList.remove('on'); b.hidden = true; }, 3000);
    } else {
      const t = document.getElementById('toast');
      if (t) { t.textContent = text; t.classList.add('on', 'err'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('on', 'err'), 2400); }
    }
  }, true);
  document.addEventListener('input', e => { if (e.target.matches('[required]')) clear(e.target); });
  document.addEventListener('change', e => { if (e.target.matches('[required]')) clear(e.target); });
  // bersihkan tanda saat sheet dibuka lagi
  document.querySelectorAll('dialog').forEach(d => d.addEventListener('close', () => { d.querySelectorAll('[required]').forEach(clear); d.querySelectorAll('.fbanner').forEach(b => { b.classList.remove('on'); b.hidden = true; }); }));
})();

// Nav header: tab aktif digulir ke tengah saat layar sempit.
(function(){
  const on = document.querySelector('.nav a.on'); if (!on) return;
  const nav = on.parentElement;
  if (nav.scrollWidth > nav.clientWidth + 4) nav.scrollTo({ left: on.offsetLeft - (nav.clientWidth - on.offsetWidth) / 2 });
})();
