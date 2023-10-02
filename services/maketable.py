import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql


DATABASE_URL = os.environ.get('DATABASE_URL')

conn = psycopg2.connect('postgres://zahidul23:HfxOLtr9FR6b@ep-cool-sea-43204625.us-east-2.aws.neon.tech/neondb')
cursor = conn.cursor()

create_table_query = '''CREATE TABLE IF NOT EXISTS seqtable
          (ID TEXT PRIMARY KEY     NOT NULL,
          SEQ TEXT NOT NULL,
          PSIPRED TEXT,
          PSICONF TEXT,
          PSISTAT INT,
          PSIMSG TEXT,

          PSSPRED TEXT,
          PSSCONF TEXT,
          PSSSTAT INT,
          PSSMSG TEXT,

          JPREDPRED TEXT,
          JPREDCONF TEXT,
          JPREDSTAT INT,
          JPREDMSG TEXT,

          RAPTORXPRED TEXT,
          RAPTORXCONF TEXT,
          RAPTORXSTAT INT,
          RAPTORXMSG TEXT,

          YASPINPRED TEXT,
          YASPINCONF TEXT,
          YASPINSTAT INT,
          YASPINMSG TEXT,

          SABLEPRED TEXT,
          SABLECONF TEXT,
          SABLESTAT INT,
          SABLEMSG TEXT,

          SSPROPRED TEXT,
          SSPROCONF TEXT,
          SSPROSTAT INT,
          SSPROMSG TEXT,
        
      MAJORITYVOTE TEXT,
      PDB TEXT,
      PDBID TEXT
); '''

cursor.execute(create_table_query)
conn.commit()
cursor.close()

if conn:
	conn.close()