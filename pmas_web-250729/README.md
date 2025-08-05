# PMAS Simulation Web Interface

This directory contains a simple web interface to run the PMAS simulation.

## Installation

This project uses Poetry for dependency management. To install the required packages, run the following command from the project's root directory (`/mnt/c/Users/m.mercaldi/radarepos/gurobi/pianificazione`):

```bash
poetry install
```

If you have already installed the dependencies for the main project, you may just need to add the web-specific ones:

requirements:
```
fastapi
uvicorn
cx_Oracle
```

```bash
poetry add fastapi "uvicorn[standard]"
```


## Running the Server

To run the web server with automatic reloading (the server will restart whenever you change a file), execute the following command from the project's root directory,
for this new sub-project run the following command from `pianificazione` subdir

```bash
poetry run uvicorn pmas_web.server:app --host 0.0.0.0 --port 8000 --reload
```

You can then access the web interface by opening your browser and navigating to [http://127.0.0.1:8000](http://127.0.0.1:8000).













---

# sql util
```sql

-----------------
-- INPUT UTENTE

----  id progetto  :  83

----  turni (1, 2, C)

----  data inizio produzione per ogni cassa
--       casse_production_dates = 
--       {'V1':'23/09/2025', 'V2':'23/10/2025', 'V3':'23/11/2025', 'V4':'23/12/2025'}

---- fattore conversione   ebom --> DRT ,  default = 3
 
---- costo orario per  MBOM, WORKINSTRUCTION, ROUTING 
--      da proporre quello nel DB , ma modificabile sul progetto scelto
select Descrizione, COSTOUNITARIOH, FLGEBOM, FLGPRODUZIONE,FLGMANUALI, OFFSETENG, OFFSETPROD 
from RST_ATTIVITAWL where Descrizione in ('M-BOM', 'WORK INSTRUCTION', 'ROUTING');
--                    COSTOUNITARIOH
-- M-BOM                  0
-- WORK INSTRUCTION      40
-- ROUTING                2
-- 
--  numero ore complessive non aggregato = 
--        Numero Eboms * Numero Dtr4 * (costo H Mbom) 
--      + Numero Eboms * Numero Dtr4 * (costo H WorkInstruction) 
--      + Numero Eboms * Numero Dtr4 * (costo H Routing)
--  es: 450 Ebom
--      3 DTR4 per Ebom
--    450 * 3 + 450 * 3 * 40 + 450 * 3 * 5 =  62100
 

 
-----------------
-- DA DATABASE

---- lista e numero di ebom, non considero gli ebom specifici per commessa
select distinct partnbr from rst_anagraficheebom where idcommessa = 71;

---- casse per ebom
--with ebom_casse as (
    select distinct an.partnbr, ap.veicolocassa
    from rst_anagraficheebom an join rst_applicazioniebom ap on ap.idanagrafica = an.id 
    where idcommessa = 71 and ap.quantita>0
    order by an.partnbr, veicolocassa
--) select distinct veicolocassa from ebom_casse
;

---- data rilascio per ogni ebom
--      minima data di rilascio per ogni applicabilita' dell'ebom
with md as (
    -- max data rilascio ingegneria, da usare come default se le datarilascio sono nulle
    select max(nvl(datarilasciofinale, dataprevistarilasciofinale)) as maxdatarilascio
    FROM rst_anagraficheebom WHERE idcommessa = 71
), 
ebom_dates as (
    select distinct ap.idanagrafica, ap.veicolocassa,ap.quantita,
    an.idcommessa, an.partnbr, an.revisione, 
    nvl(nvl(an.datarilasciofinale, an.dataprevistarilasciofinale), 
            (select maxdatarilascio from md) 
        ) as datarilascio  
    from (
        SELECT id, idcommessa, partnbr, datarilasciofinale, dataprevistarilasciofinale, revisione
        FROM (
            SELECT id, idcommessa, partnbr, datarilasciofinale, dataprevistarilasciofinale, revisione,
                   ROW_NUMBER() OVER (PARTITION BY partnbr ORDER BY revisione DESC) as rn
            FROM rst_anagraficheebom
            WHERE idcommessa = 71
        ) t
        WHERE rn = 1  order by partnbr
    ) an
    join rst_applicazioniebom ap on ap.idanagrafica = an.id 
    Where ap.quantita>0
    order by an.partnbr, veicolocassa
)
select partnbr, min(datarilascio) as datarilascio
from ebom_dates group by partnbr;

---- offset ingegneria e produzione
--         da sommare alla data di rilascio per avere la deadline dell'mbom
--         da sottrarre alla data di produzione per avere le deadline di workinstruction e routing
select Descrizione, FLGEBOM, FLGPRODUZIONE, FLGMANUALI, OFFSETENG, OFFSETPROD 
from RST_ATTIVITAWL where Descrizione in ('M-BOM', 'WORK INSTRUCTION', 'ROUTING');
--                    OFFSETENG   OFFSETPROD
-- M-BOM                 10           0
-- WORK INSTRUCTION       0          20
-- ROUTING                0           5




-----------------
-- CALCULATED

-- ebom_production_dates
--    from  casse_production_dates and  database  ... ?

-- eboms
--     {  "id": "EBOM1.DRT2",
--     "eng_release_date": datetime(2024, 5, 2),
--     "phases": [
--         {"id": 0, "name": "mbom", "deadline": datetime(2024, 5, 8), "cost": 45.2, "remaining_cost": 45.2, "active_worker": None},
--         {"id": 0, "name": "workinstruction", "deadline": datetime(2026, 5, 18), "cost": 48.1, "remaining_cost": 48.1, "active_worker": None},
--         {"id": 0, "name": "routing", "deadline": datetime(2028, 6, 2), "cost": 36.5, "remaining_cost": 36.5, "active_worker": None}
--     ] },
-- dove:
--    eng_release_date : datarilascio da db
--    deadline ebom = rst_anagraficheebom.datarilascio(EBOM) + RST_ATTIVITAWL.OFFSETENG(MBOM)
--    deadline workinstruction = minima(ebom_production_dates(EBOM su Cassa)) - RST_ATTIVITAWL.OFFSETPROD(WORKINSTRUCTION)
--    deadline routing = minima(ebom_production_dates(EBOM su Cassa)) - RST_ATTIVITAWL.OFFSETPROD(ROUTING)
 
-- START_DATE simulazione  =  MIN(data rilascio ingegneria)

-- ELAPSED_DAYS =  MIN(ebom_production_dates)  -  START_DATE


/*
SELECT min(to_date(datainizio,'dd/mm/yyyy'))  FROM RST_IMPORTAZIONEPIANOPROD WHERE IDCOMMESSA = 24 AND CASSA ='DC1' AND TRENOCOMMERCIALE='1' AND workstation='WSL010';
SELECT * FROM RST_IMPORTAZIONEPIANOPROD WHERE IDCOMMESSA = 24 AND CASSA ='DC1' AND TRENOCOMMERCIALE='1' AND workstation='WSL010';
desc RST_IMPORTAZIONEPIANOPROD;

select distinct idcommessa from RST_IMPORTAZIONEPIANOPROD order by idcommessa;
select distinct id from rst_verecommesse order by id;
select * from RST_IMPORTAZIONEPIANOPROD;
select distinct id from rst_verecommesse order by id;


select * from rst_anagraficheebom where idcommessa=24;
select distinct idcommessa from RST_IMPORTAZIONEPIANOPROD
where idcommessa is not null
and idcommessa in (select distinct idcommessa from rst_anagraficheebom);
*/
```



datarilasciofinale e dataprevistarilascio finale in RST_ANAGRAFICHEEBOM
erano varchar2 in formati vari,
risanato il db per il progetto 88:

```sql
ALTER TABLE RST_ANAGRAFICHEEBOM ADD (
    DATARILASCIOFINALE_DATE DATE,
    DATAPREVISTARILASCIOFINALE_DATE DATE
);


CREATE OR REPLACE FUNCTION parse_date(p_str IN VARCHAR2)
RETURN DATE
IS
BEGIN
    IF REGEXP_LIKE(p_str, '^\d{8}$') THEN
        RETURN TO_DATE(p_str, 'YYYYMMDD');
    ELSIF REGEXP_LIKE(p_str, '^\d{2}/\d{2}/\d{4}$') THEN
        RETURN TO_DATE(p_str, 'DD/MM/YYYY');
    ELSIF REGEXP_LIKE(p_str, '^\d{2}-\d{2}-\d{4}$') THEN
        RETURN TO_DATE(p_str, 'DD-MM-YYYY');
    ELSIF REGEXP_LIKE(p_str, '^\d{4}-\d{2}-\d{2}$') THEN
        RETURN TO_DATE(p_str, 'YYYY-MM-DD');
    ELSE
        RETURN NULL;
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        RETURN NULL;
END parse_date;
/


create or replace PROCEDURE risanamento_date_progetto(midPrg Number) IS
    CURSOR c IS
        SELECT id, datarilasciofinale, dataprevistarilasciofinale
        FROM rst_anagraficheebom Where idCommessa = midPrg;

    v_date1 DATE;
    v_date2 DATE;
BEGIN
    FOR rec IN c LOOP
        v_date1 := parse_date(rec.datarilasciofinale);
        v_date2 := parse_date(rec.dataprevistarilasciofinale);

        UPDATE rst_anagraficheebom
        SET
            datarilasciofinale_date = v_date1,
            dataprevistarilasciofinale_date = v_date2
        WHERE id = rec.id;
    END LOOP;

    COMMIT;
END risanamento_date_progetto;

-- eseguito per progetto  71
--     ci sono date rilascio nulle
```





---








# prompt to gemini

> I need a small web interface that allow the user to input the vaues in pmas_configuration with some
  instruction that I will give you


> yes, all good, I need to use the python executable that is in the ../.venv environment,  take care
  that we are usin poetry. Then say me what do you prefer: 1) when the basic structure is ready we can
  refine the inputs or 2) I will give now more detailed specification on how the user must input data


I would prefer option 2. If you provide the detailed specifications for the inputs now, I can build a
  more accurate and user-friendly interface from the start. This will likely be faster than refining a
  basic structure later.

Before I proceed, I have a few questions to ensure I build the interface to your exact specifications:


   1. SQL Connection: The sql_connection_params (host, port, username, password) are sensitive. Do you
      want to allow users to edit these from the web interface, or should they remain fixed in the code?
   2. Shift Configuration: The SHIFT_CONFIG is a dictionary of shifts. How would you like the user to
      edit this? I can provide a simple text area where the user can paste a JSON-like structure, or I
      can build a more interactive table where the user can add/remove shifts and edit their start time
      and duration.
   3. Casse Production Dates: Similar to the shifts, how should the casse_production_dates be edited? A
      text area or an interactive table?
   4. Database Values: The section FROM DATABASE contains parameters like NUM_EBOMS,
      deadline_offset_mbom, etc. Should these be editable by the user, or are they fixed values that my
      web interface should not expose?
   5. Tick Interval: The TICK is currently set to 30 minutes. Would you like this to be a configurable
      number in the UI (e.g., the user enters "30" for 30 minutes)?


> 1. sql connection param will remain fixed in the code.    2: user can choose the number of shift        │
│   (2 or 3) and then for every shift he must enter the start and duration.   3: the user must        │
│   enter an ID_PROGETTO, then a backend query must be performed using the getCasse() function        │
│   in pmas_sql.py that returns a list of casse, then for every cassa the user must input a           │
│   production deadline date.  4: no, all these values will be retrieved from database.  5: no        │
│   TICK is a constant in the code       

poetry add fastapi uvicorn cx_Oracle

poetry run python server.py

poetry show uvicorn


   1. Open the Web Page: The user will open their browser and navigate to the web server's address (e.g.,
      http://localhost:8000). They will see the "PMAS Simulation" interface.

   2. Enter Project ID: The first field is "ID Progetto". The user will enter the project number here.


   3. Fetch `Casse`: After entering the Project ID, the user will click the "Get Casse" button. This
      action triggers the following:
       * The browser sends the Project ID to the backend.
       * The backend server uses the getCasse() function from your pmas_sql.py script to query the
         database for all the casse associated with that project.
       * The server returns the list of casse names to the web page.
       * The interface will dynamically update, showing each cassa name followed by a date input field,
         allowing the user to set a production deadline for each one.


   4. Configure Shifts:
       * The user will select the desired number of shifts (2 or 3) from the "Number of Shifts" dropdown
         menu.
       * Based on the selection, the interface will automatically display the correct number of input
         fields. For each shift, the user must enter a start time (e.g., "06:00") and a duration in
         hours (e.g., "7.5").


   5. Set Other Parameters: The user can then review and modify the other pre-filled numeric values for
      the simulation:
       * Multiplier EBOM to DTR
       * Hourly Cost MBOM
       * Hourly Cost Work Instruction
       * Hourly Cost Routing


   6. Review All Inputs: Before running the simulation, the user will click a new "Review Inputs" button.
       * This will gather all the data entered on the page.
       * It will send the data to a new API endpoint on the server.
       * The server will format this data into a clean, readable structure (JSON) and send it back.
       * The web page will then display this formatted data, allowing the user to verify that everything
         is correct.


   7. Run Simulation: Once the user is satisfied with the reviewed inputs, they will click the "Run
      Simulation" button to start the actual simulation process.
