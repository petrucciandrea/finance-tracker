import { Controller, LegalLayout } from '@/components/layout/LegalLayout'

export function TermsPage() {
  return (
    <LegalLayout title="Termini di servizio">
      <p>
        Usando Finanze accetti questi termini. Il servizio è gestito da <Controller />.
      </p>

      <h2>1. Il servizio</h2>
      <p>
        Finanze è uno strumento per tenere traccia di conti, spese, investimenti e beni, e per pianificare il
        risparmio. È offerto gratuitamente e «così com&apos;è», senza garanzie di disponibilità continua né assenza di
        errori.
      </p>

      <h2>2. Non è consulenza</h2>
      <p>
        Calcoli, stime e suggerimenti (compresi quelli su tasse, contributi, scadenze fiscali e accantonamenti del
        regime forfettario) sono indicativi e non sostituiscono un commercialista, un consulente finanziario o un
        professionista abilitato. Le decisioni che prendi restano tue.
      </p>

      <h2>3. Dati di mercato</h2>
      <p>
        Cambi e prezzi provengono da fonti di terze parti e possono essere ritardati, incompleti o errati. Non
        garantiamo la loro accuratezza; il valore del patrimonio mostrato è una stima.
      </p>

      <h2>4. Registrazione e account</h2>
      <p>
        Per usare il servizio devi essere maggiorenne. La registrazione è soggetta ad approvazione e possiamo
        rifiutare o sospendere un account, in particolare in caso di abuso. Sei responsabile di custodire la tua
        password e dei dati che inserisci; dichiari di avere il diritto di inserirli, compresi quelli di terzi come i
        nomi dei tuoi clienti.
      </p>

      <h2>5. Uso corretto</h2>
      <p>
        Non puoi tentare di accedere ad account altrui, aggirare i limiti tecnici, sovraccaricare il servizio o usarlo
        per attività illecite. Non inserire dati particolari (salute, opinioni religiose o politiche, ecc.): vedi
        l&apos;informativa sulla privacy.
      </p>

      <h2>6. Responsabilità</h2>
      <p>
        Nei limiti consentiti dalla legge, non rispondiamo di perdite o danni derivanti dall&apos;uso o dal mancato uso
        del servizio, da errori nei calcoli o nei dati di mercato, o dalla perdita di dati. Ti consigliamo di
        conservare copie dei dati che ritieni importanti. Restano ferme le responsabilità che la legge non permette di
        escludere.
      </p>

      <h2>7. Modifiche e chiusura</h2>
      <p>
        Possiamo modificare il servizio o questi termini, o interromperlo, dandone avviso ragionevole. Puoi smettere di
        usarlo e chiedere la cancellazione dei tuoi dati in qualsiasi momento, come descritto nell&apos;informativa
        sulla privacy.
      </p>

      <h2>8. Legge applicabile</h2>
      <p>
        Questi termini sono regolati dalla legge italiana. Se sei un consumatore restano valide le tutele inderogabili
        e il foro previsto dalla legge del tuo Paese di residenza.
      </p>
    </LegalLayout>
  )
}
