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
  dlg.querySelector('[data-del]').action = `/tx/${d.id}/delete`;
  dlg.querySelector('h3').textContent = d.kind === 'income' ? 'Edit pemasukan' : 'Edit pengeluaran';
  dlg.querySelector('#edit-status-wrap').hidden = d.kind !== 'expense';
});
// Konfirmasi hapus
document.addEventListener('submit', e => {
  if (e.target.matches('[data-confirm]') && !confirm(e.target.dataset.confirm)) e.preventDefault();
});
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
