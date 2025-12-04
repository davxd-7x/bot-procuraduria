import sqlite3

DB = 'procuraduria.db'

alterations = [
    ("documentos", "ius", "TEXT"),
    ("documentos", "attached_iuc", "TEXT"),
    ("casos", "visibilidad", "TEXT DEFAULT 'PUBLICO'"),
    ("casos", "fecha_cierre", "TIMESTAMP")
]

conn = sqlite3.connect(DB)
cur = conn.cursor()

for table, column, coltype in alterations:
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    if column in cols:
        print(f"- La columna '{column}' ya existe en '{table}'")
    else:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
            print(f"+ Añadida columna '{column}' a tabla '{table}'")
        except Exception as e:
            print(f"! Error añadiendo {column} a {table}: {e}")

conn.commit()
conn.close()

print("Migración completa. Si quieres, reinicia el bot ahora.")
