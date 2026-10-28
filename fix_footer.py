path = r"C:\Users\Player 1\Desktop\GestiStore\Tienda\static\tienda\css\style.css"
c = open(path, "r", encoding="utf-8").read()

# Remove gradient footer
old = """[data-theme="dark"] .footer {
  background: linear-gradient(160deg, var(--amp-night), #2b2858);
  border-top: none;
}
[data-theme="dark"] .footer::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--amp-primary), var(--amp-light) 60%, var(--amp-copper));
  display: block;
}
[data-theme="dark"] .footer .brand-title { color: var(--amp-white); }
[data-theme="dark"] .footer .brand-sub { color: var(--amp-copper-soft); }
[data-theme="dark"] .footer .brand-logo { background: rgba(255,255,255,.08); box-shadow: inset 0 -3px 0 var(--amp-copper); }
[data-theme="dark"] .footer-contact a { color: var(--amp-soft); }
[data-theme="dark"] .footer-contact a:hover { color: var(--amp-white); }
[data-theme="dark"] .footer-right a { color: var(--amp-white); }
[data-theme="dark"] .footer-copy { color: var(--amp-soft); }
"""
new = """[data-theme="dark"] .footer {
  background: var(--amp-white);
  color: var(--amp-text);
  border-top: 1px solid var(--amp-border);
}
[data-theme="dark"] .footer::before { display: none; }
[data-theme="dark"] .footer .brand-title { color: var(--amp-night); }
[data-theme="dark"] .footer .brand-sub { color: var(--amp-copper); }
[data-theme="dark"] .footer .brand-logo { background: var(--amp-night); box-shadow: inset 0 -3px 0 var(--amp-copper); }
[data-theme="dark"] .footer-contact a { color: var(--amp-muted); }
[data-theme="dark"] .footer-contact a:hover { color: var(--amp-text); }
[data-theme="dark"] .footer-right a { color: var(--amp-muted); }
[data-theme="dark"] .footer-right a:hover { color: var(--amp-text); }
[data-theme="dark"] .footer-copy { color: var(--amp-muted); }
"""
if old in c:
    c = c.replace(old, new)
    open(path, "w", encoding="utf-8").write(c)
    print("done")
else:
    print("notfound")
