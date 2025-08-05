import cx_Oracle

from pmas_configuration import PmasConfiguration
from pmas_util import PmasLoggerSingleton
import hashlib
import datetime

conf: PmasConfiguration = None
glog: PmasLoggerSingleton = None
db = None
dbcache = {}
# _mme  ......... rimuovi dbcache
dbcacheenabled = False # _mme review 



class PmasOracleDBClient:
    def __init__(self, host, port, service_name, username, password):
        dsn = cx_Oracle.makedsn(host, port, service_name=service_name)
        self.connection = cx_Oracle.connect(user=username, password=password, dsn=dsn)


    def execute_query_test(self, query, params=None):
        #query = "SELECT * FROM DUAL"
        query = "select user from dual"
        #query = "SELECT * FROM all_tables WHERE ROWNUM <= 5"
        print("[DEBUG] Query:", query)
        cursor = self.connection.cursor()
        cursor.execute(query)
        print(cursor.fetchall())
        return []


    def execute_query(self, query, params=None):
        glog.debug("Query: %s", query)
        glog.debug("Params: %s", params)
        
        query_hash = hashlib.sha256(query.encode('utf-8')).hexdigest()
        # Check cache: valid for 10 minutes
        if dbcacheenabled and query_hash in dbcache:
            entry = dbcache[query_hash]
            if (datetime.datetime.now() - entry['date']).total_seconds() < 600 and entry['params'] == params:
                glog.info(f"_mme get result from db cache")
                return entry['result']
        
        cursor = self.connection.cursor()
        try:
            cursor.execute(query, params or {})
            columns = [col[0] for col in cursor.description]
            glog.debug("Columns: %s", columns)
            rows = cursor.fetchall()
            glog.debug("Row count: %d", len(rows))
            result = [dict(zip(columns, row)) for row in rows]
            if dbcacheenabled:
                dbcache[query_hash] = {
                    'result': result,
                    'date': datetime.datetime.now(),
                    'params': params
                }
            return result
        except cx_Oracle.DatabaseError as e:
            error, = e.args
            glog.error("Oracle Database Error: %s", error.message)
            raise

    def close(self):
        self.connection.close()






class PmasSql:
    def __init__(self, pconf):
        global conf, glog, db
        glog = PmasLoggerSingleton.get_logger()
        conf = pconf
        db = None

    def start(self):
        global db
        db = PmasOracleDBClient(
            host=conf.sql_connection_params["host"],
            port=conf.sql_connection_params["port"],
            service_name=conf.sql_connection_params["service_name"],
            username=conf.sql_connection_params["username"],
            password=conf.sql_connection_params["password"]
        )
        
    def end(self):
        global db
        db.close()
        db = None


    # casse per project
    # the user will fill the ddelivery date for every cassa
    def getCasse(self, idprogetto):
        glog.debug(f"\n ---------- %s", self.getCasse.__name__)
        query = """
            select distinct ap.veicolocassa
            from rst_anagraficheebom an join rst_applicazioniebom ap
            on an.id = ap.idanagrafica
            where an.idcommessa = :idprogetto
            order by ap.veicolocassa
        """
        result = db.execute_query(query, {"idprogetto": idprogetto})
        for row in result:
            glog.debug(" > Row: %s", row)
        return [row['VEICOLOCASSA'] for row in result]


    # hourly cost and daily offset for every ebom phase: mbom, workinstruction, routing
    def getPhasestOffsetAndCost(self):
        glog.debug(f"\n ---------- %s", self.getPhasestOffsetAndCost.__name__)
        query = """
            select Descrizione, 
            GREATEST(1, COSTOUNITARIOH) AS COSTOUNITARIOH, 
            GREATEST(OFFSETENG, OFFSETPROD ) as OFFSET
            from RST_ATTIVITAWL where Descrizione in ('M-BOM', 'WORK INSTRUCTION', 'ROUTING')
        """
        result = db.execute_query(query)
        ret = {}
        for row in result:
            #glog.info("Row: %s", row)
            ret[row['DESCRIZIONE'].replace('-', '').replace(' ', '').lower()] = row
        ret['workinstruction']['OFFSET'] *= -1;  # workinstruction and routing must be subtracted to production deadline date
        ret['routing']['OFFSET'] *= -1;
        for key, value in ret.items():
            glog.debug(" > %s: %s", key, value)
        return ret


    # number and list of eboms, we do not consider specific ebom for commessa,
    # but only aggregated by progetto
    def getAllEbomsLastRev(self, idprogetto):
        glog.debug(f"\n ---------- %s", self.getAllEbomsLastRev.__name__)
        query = """
            with all_ebom_lastrev as (
                SELECT id, idcommessa, partnbr, revisione,
                ROW_NUMBER() OVER (PARTITION BY partnbr ORDER BY revisione DESC) as rn
                FROM rst_anagraficheebom
                WHERE idcommessa = :idprogetto
            ) select distinct partnbr from all_ebom_lastrev
        """
        result = db.execute_query(query, {"idprogetto": idprogetto})
        for row in result:
            glog.debug(" > Row: %s", row)
        return [row['PARTNBR'] for row in result]


    # get max ebom release date, to be used if other dates are null
    def getMaxEbomReleaseDate(self, idprogetto):
        glog.debug(f"\n ---------- %s", self.getMaxEbomReleaseDate.__name__)
        query = """
            select max(nvl(datarilasciofinale, dataprevistarilasciofinale)) as maxDataRilascio
            FROM rst_anagraficheebom WHERE idcommessa = :idprogetto
        """
        result = db.execute_query(query, {"idprogetto": idprogetto})
        for row in result:
            glog.debug(" > Row: %s", row)
        return result


    def getAllEbomsWithReleaseDates(self, idprogetto):
        glog.debug(f"\n ---------- %s", self.getAllEbomsWithReleaseDates.__name__)
        query = """
            with md as (
                -- get max data rilascio finale to be used as a default value
                select max(nvl(datarilasciofinale_date, dataprevistarilasciofinale_date)) as maxdatarilascio
                FROM rst_anagraficheebom WHERE idcommessa = :idprogetto
            ),
            ebom_and_dates as (
                select distinct
                    an.idcommessa, an.partnbr, an.rev, ap.idanagrafica, ap.veicolocassa, ap.quantita,
                    nvl(nvl(an.datarilasciofinale_date, an.dataprevistarilasciofinale_date),
                                    (select maxdatarilascio from md) ) as datarilascio  
                from (
                    SELECT id, idcommessa, partnbr, rev, datarilasciofinale_date, dataprevistarilasciofinale_date
                    FROM (
                        SELECT id, idcommessa, partnbr, trovaletterarevisione(revisione) as Rev, datarilasciofinale_date, dataprevistarilasciofinale_date,
                            ROW_NUMBER() OVER (PARTITION BY partnbr ORDER BY revisione DESC) as rn
                        FROM rst_anagraficheebom
                        WHERE substr(partnbr,1,3) != 'MNG'
                        And statoebom=0
                        And idcommessa = :idprogetto
                    ) t
                    WHERE rn = 1  order by partnbr
                ) an
                Inner join rst_applicazioniebom ap on ap.idanagrafica = an.id
                where ap.quantita>0
                order by an.partnbr, ap.idanagrafica, veicolocassa
            )
            select distinct idanagrafica, partnbr,rev, datarilascio, veicolocassa
            from ebom_and_dates 
            where datarilascio > to_date('2022-01-01', 'YYYY-MM-DD') and datarilascio < to_date('2025-01-01', 'YYYY-MM-DD')
            order by partnbr, veicolocassa
        """  # _mme togli condizione su datarilascio e metti controlli su date produzione non valide immesse da utente
        # _mme   ........... togli condizione su datarilascio
        result = db.execute_query(query, {"idprogetto": idprogetto})
        for row in result:
            glog.debug(" > Row: %s", row)
        return result


    def getAllEbomsWithSkills(self, idprogetto):
        glog.debug(f"\n ---------- %s", self.getAllEbomsWithSkills.__name__)
        query = """
            select distinct trim(a.partnbr) as partnbr, trim(s.codice) as codice, trim(s.descrizione) as descrizione 
            from rst_anagraficheebom a
            inner join rst_skillanaebom sa on a.id = sa.idanagrafica
            inner join rst_skill s on sa.idskill = s.id
            where a.idcommessa = :idprogetto
            order by partnbr
        """
        result = db.execute_query(query, {"idprogetto": idprogetto})
        for row in result:
            glog.debug(" > Row: %s", row)
        return result


    def get_all_data_from_database(self):
        glog.debug(f"\n ---------- database ----------")
        self.getCasse(conf.ID_PROGETTO)
        self.getPhasestOffsetAndCost()
        self.getMaxEbomReleaseDate(conf.ID_PROGETTO)
        self.getAllEbomsLastRev(conf.ID_PROGETTO)
        self.getAllEbomsWithReleaseDates(conf.ID_PROGETTO)
        glog.debug(f" ---------- ----------")
