path = r"C:\Users\Player 1\Desktop\GestiStore\Tienda\static\tienda\css\style.css"
c = open(path, "r", encoding="utf-8").read()

old = """[data-theme="dark"] .brand-sub {
  color: var(--amp-accent);
  font-weight: 600;
  letter-spacing: 0.08em;
}"""
new = """[data-theme="dark"] .brand-sub {
  color: #b9bfd9;
  font-weight: 600;
  letter-spacing: 0.08em;
}"""
if old in c:
    c = c.replace(old, new)
    open(path, "w", encoding="utf-8").write(c)
    print("done")
else:
    print("notfound")
