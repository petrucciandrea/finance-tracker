import { Controller, LegalLayout } from '@/components/layout/LegalLayout'
import { LEGAL } from '@/lib/legal'

export function PrivacyPage() {
  return (
    <LegalLayout title="Informativa sulla privacy">
      <p>
        Questa informativa spiega quali dati personali tratta Finanze, perché, per quanto tempo e quali diritti hai
        (Regolamento UE 2016/679, «GDPR»).
      </p>

      <h2>1. Titolare del trattamento</h2>
      <p>
        <Controller />
      </p>

      <h2>2. Quali dati trattiamo</h2>
      <ul>
        <li>
          <strong>Dati dell&apos;account:</strong> email, password (conservata solo come hash, mai in chiaro), valuta
          base e, se li inserisci, nome, cognome, data di nascita e tipo di attività lavorativa.
        </li>
        <li>
          <strong>Dati che inserisci tu:</strong> conti, movimenti, categorie, investimenti, beni, fatture e dati
          fiscali, compresi i nomi dei tuoi clienti e il testo libero di descrizioni e note.
        </li>
        <li>
          <strong>Dati tecnici:</strong> indirizzo IP e log di accesso, usati per sicurezza e prevenzione degli abusi;
          data e versione dell&apos;accettazione di questa informativa e dei termini.
        </li>
      </ul>
      <p>
        <strong>Non inserire dati particolari</strong> (salute, convinzioni religiose o politiche, appartenenza
        sindacale, vita sessuale, dati biometrici) nei campi di testo libero: il servizio non ne ha bisogno e non è
        progettato per proteggerli in modo specifico. Se li inserisci, lo fai di tua iniziativa.
      </p>

      <h2>3. Perché e su quale base</h2>
      <ul>
        <li>Fornirti il servizio che hai richiesto registrandoti (art. 6.1.b GDPR, esecuzione del contratto).</li>
        <li>
          Garantire la sicurezza del servizio e prevenire abusi, ad esempio limitando i tentativi di accesso (art.
          6.1.f, legittimo interesse).
        </li>
        <li>Adempiere a obblighi di legge, se previsti (art. 6.1.c).</li>
      </ul>
      <p>
        Non facciamo profilazione, non prendiamo decisioni automatizzate che ti riguardano, non mostriamo pubblicità e
        non vendiamo né cediamo i tuoi dati.
      </p>

      <h2>4. Per quanto tempo li conserviamo</h2>
      <p>
        Finché il tuo account è attivo. Se chiedi la cancellazione, eliminiamo i tuoi dati. Le copie di backup vengono
        sovrascritte alla loro naturale rotazione. I log tecnici sono conservati per il tempo necessario alla
        sicurezza.
      </p>

      <h2>5. A chi vengono comunicati</h2>
      <ul>
        <li>
          <strong>Hosting:</strong> {LEGAL.hosting || '[fornitore di hosting da indicare]'}, che ospita
          l&apos;applicazione e il database in qualità di responsabile del trattamento.
        </li>
        <li>
          <strong>Invio email:</strong> il servizio di posta usato per le notifiche di registrazione e approvazione.
        </li>
        <li>
          <strong>Dati di mercato:</strong> per cambi e prezzi il server interroga Frankfurter (Banca Centrale
          Europea), Yahoo Finance e CoinGecko. Ricevono solo valute, simboli, date e il testo che digiti per cercare
          un titolo, insieme all&apos;indirizzo IP del server: non i tuoi dati personali né il tuo account. Yahoo e
          CoinGecko possono trovarsi fuori dallo Spazio economico europeo.
        </li>
      </ul>

      <h2>6. Cookie e archiviazione locale</h2>
      <p>
        Non usiamo cookie, strumenti di analisi né tracciamento, e non carichiamo risorse da servizi di terze parti
        (il font è servito dal sito stesso). Salviamo nel tuo browser solo due informazioni tecniche, necessarie al
        funzionamento e che non richiedono consenso: il token che mantiene la sessione attiva e la tua preferenza di
        tema (chiaro/scuro).
      </p>

      <h2>7. I tuoi diritti</h2>
      <p>
        Puoi chiedere accesso, rettifica, cancellazione, limitazione, portabilità dei tuoi dati e opporti al
        trattamento scrivendo a {LEGAL.email ? <a className="link" href={`mailto:${LEGAL.email}`}>{LEGAL.email}</a> : '[contatto non configurato]'}
        . Puoi anche fare da solo, dal tuo profilo (sezione «Dati e privacy»): scaricare una copia dei dati in
        formato JSON ed eliminare definitivamente l&apos;account. Hai inoltre il diritto di proporre reclamo al{' '}
        <a className="link" href="https://www.garanteprivacy.it" target="_blank" rel="noreferrer">
          Garante per la protezione dei dati personali
        </a>
        .
      </p>

      <h2>8. Sicurezza</h2>
      <p>
        Adottiamo misure ragionevoli: password protette da hash, connessioni cifrate, limitazione dei tentativi di
        accesso e approvazione manuale dei nuovi account. Nessun sistema è sicuro al cento per cento: in caso di
        violazione dei dati che ti riguardi ti informeremo come richiesto dalla legge.
      </p>

      <h2>9. Modifiche</h2>
      <p>
        Se questa informativa cambia in modo rilevante aggiorneremo la versione e la data in alto e, quando richiesto,
        ti chiederemo di nuovo di accettarla.
      </p>
    </LegalLayout>
  )
}
