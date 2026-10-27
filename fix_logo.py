path = r"C:\Users\Player 1\Desktop\GestiStore\Tienda\static\tienda\css\style.css"
c = open(path, "r", encoding="utf-8").read()

if "--amp-night" not in c:
    c = c.replace("--amp-header-height: 80px;", "--amp-header-height: 80px;\n  --amp-night: #353166;")

old = """.brand-logo {
  background: linear-gradient(145deg, var(--amp-primary), var(--amp-primary-strong));
  box-shadow: none;
  border-radius: 10px;
}"""
new = """.brand-logo {
  background: var(--amp-night);
  box-shadow: inset 0 -3px 0 var(--amp-accent);
  border-radius: 10px;
  color: var(--amp-white);
}"""
if old in c:
    c = c.replace(old, new)

old2 = """.footer .brand-logo {
  background: linear-gradient(145deg, var(--amp-primary), var(--amp-primary-strong));
  box-shadow: none;
}"""
new2 = """.footer .brand-logo {
  background: var(--amp-night);
  box-shadow: inset 0 -3px 0 var(--amp-accent);
}"""
if old2 in c:
    c = c.replace(old2, new2)

old3 = """[data-theme="dark"] .brand-logo {
  background: linear-gradient(145deg, var(--amp-primary), var(--amp-primary-strong));
  box-shadow: none;
}"""
new3 = """[data-theme="dark"] .brand-logo {
  background: var(--amp-night);
  box-shadow: inset 0 -3px 0 var(--amp-accent);
}"""
if old3 in c:
    c = c.replace(old3, new3)

old4 = """[data-theme="dark"] .footer .brand-logo {
  background: linear-gradient(145deg, var(--amp-primary), var(--amp-primary-strong));
  box-shadow: none;
}"""
new4 = """[data-theme="dark"] .footer .brand-logo {
  background: var(--amp-night);
  box-shadow: inset 0 -3px 0 var(--amp-accent);
}"""
if old4 in c:
    c = c.replace(old4, new4)

open(path, "w", encoding="utf-8").write(c)
print("done")
