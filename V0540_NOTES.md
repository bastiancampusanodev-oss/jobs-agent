# v0.5.40 — Read-only submit verification retries

- The final submit remains a single irreversible click.
- The original job page is re-read up to 3 times after that click.
- Only read-only probes are retried; there is no submit retry path.
- Supports delayed "Ver tu postulación" propagation.
- Recognizes preview/draft text such as "Aún no ha sido enviada".
- Network/probe errors fail closed to SUBMIT_UNKNOWN.
