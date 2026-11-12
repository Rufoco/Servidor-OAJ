/* compartido/limpiar-ips.js
 * Agrega un boton "Limpiar" debajo de cada cuadro de texto donde se pegan IPs (textarea).
 * Vacia el cuadro, avisa a la pagina para que actualice el contador y deja el cursor listo.
 */
(function () {
  function yaTieneLimpiar(ta) {
    var cont = ta.parentElement;
    if (!cont) return false;
    var btns = cont.querySelectorAll('button');
    for (var i = 0; i < btns.length; i++) {
      if (/limpiar/i.test(btns[i].textContent || '') && !btns[i].hasAttribute('data-gl-limpiar')) return true;
    }
    return false;
  }

  function agregar(ta) {
    if (ta.getAttribute('data-gl-listo')) return;
    ta.setAttribute('data-gl-listo', '1');
    if (yaTieneLimpiar(ta)) return;
    var b = document.createElement('button');
    b.type = 'button';
    b.textContent = 'Limpiar';
    b.title = 'Vaciar el cuadro de IPs';
    b.setAttribute('data-gl-limpiar', '1');
    b.style.cssText = 'margin-top:.4rem;padding:.3rem .8rem;border:1px solid var(--border,#c9ced8);' +
      'border-radius:.5rem;background:var(--surface-2,#f8f9fb);color:var(--muted,#5a6170);' +
      'font:inherit;font-size:.8rem;cursor:pointer';
    b.onclick = function () {
      ta.value = '';
      ta.dispatchEvent(new Event('input', { bubbles: true }));
      ta.dispatchEvent(new Event('change', { bubbles: true }));
      ta.focus();
    };
    ta.insertAdjacentElement('afterend', b);
  }

  function revisar() {
    var tas = document.querySelectorAll('textarea');
    for (var i = 0; i < tas.length; i++) agregar(tas[i]);
  }

  function iniciar() {
    revisar();
    new MutationObserver(revisar).observe(document.body, { childList: true, subtree: true });
  }

  if (document.body) iniciar();
  else document.addEventListener('DOMContentLoaded', iniciar);
})();
