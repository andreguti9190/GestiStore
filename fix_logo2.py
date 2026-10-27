path = r"C:\Users\Player 1\Desktop\GestiStore\Tienda\static\tienda\css\style.css"
c = open(path, "r", encoding="utf-8").read()

# Force logo styles
old = """.brand-logo {
  background: var(--amp-night);
  box-shadow: inset 0 -3px 0 var(--amp-accent);
  border-radius: 10px;
  color: var(--amp-white);
}"""
new = """.brand-logo {
  background: #353166 !important;
  box-shadow: inset 0 -3px 0 #ad7d43 !important;
  border-radius: 10px;
  color: #ffffff !important;
}"""
c = c.replace(old, new)

old2 = """.footer .brand-logo {
  background: var(--amp-night);
  box-shadow: inset 0 -3px 0 var(--amp-accent);
}"""
new2 = """.footer .brand-logo {
  background: #353166 !important;
  box-shadow: inset 0 -3px 0 #ad7d43 !important;
}"""
c = c.replace(old2, new2)

old3 = """[data-theme="dark"] .brand-logo {
  background: var(--amp-night);
  box-shadow: inset 0 -3px 0 var(--amp-accent);
  color: var(--amp-white);
}"""
new3 = """[data-theme="dark"] .brand-logo {
  background: #353166 !important;
  box-shadow: inset 0 -3px 0 #ad7d43 !important;
  color: #ffffff !important;
}"""
c = c.replace(old3, new3)

old4 = """[data-theme="dark"] .footer .brand-logo {
  background: var(--amp-night);
  box-shadow: inset 0 -3px 0 var(--amp-accent);
}"""
new4 = """[data-theme="dark"] .footer .brand-logo {
  background: #353166 !important;
  box-shadow: inset 0 -3px 0 #ad7d43 !important;
}"""
c = c.replace(old4, new4)

open(path, "w", encoding="utf-8").write(c)
print("done")
