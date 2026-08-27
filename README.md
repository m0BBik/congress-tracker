# Rejestr Transakcji Kongresu

Darmowa, samoaktualizująca się aplikacja śledząca jawne transakcje giełdowe
senatorów USA (dane z formularzy PTR wymaganych przez STOCK Act).

- `index.html` — sama aplikacja (statyczny plik, bez backendu)
- `data/senate_transactions.json` — dane transakcji (startowo 550 realnych
  rekordów z 2019–2020, potem dopisywane przez scraper)
- `data/senators_party.json` — aktualna lista 100 senatorów z partią,
  z oficjalnego publicznego projektu `unitedstates/congress-legislators`
- `scraper/scrape_senate.py` — scraper efdsearch.senate.gov (Playwright)
- `scraper/update_party.py` — odświeża listę senatorów, partii i komisji senackich
- `scraper/compute_performance.py` — liczy zwrot z każdej transakcji względem
  cen rynkowych (Stooq) i zapisuje wynik do pliku danych — robi to **po
  stronie serwera** w GitHub Actions, nie w przeglądarce użytkownika (Stooq
  nie obsługuje CORS, więc pobieranie z przeglądarki zawodziło)
- `.github/workflows/update-data.yml` — uruchamia oba skrypty **codziennie**
  za darmo na GitHub Actions i commituje nowe dane

## Jak to uruchomić (5 minut, zero kosztów)

1. **Załóż nowe, puste repozytorium na GitHub** (może być prywatne albo
   publiczne — dla GitHub Pages za darmo musi być publiczne, chyba że masz
   plan Pro/Team).
2. Wgraj do niego całą zawartość tego folderu (np. przez stronę GitHub —
   "Add file → Upload files" — albo `git push`, jeśli znasz git).
3. Włącz **GitHub Pages**: Settings → Pages → Source: "Deploy from a
   branch" → branch `main`, folder `/ (root)` → Save. Po chwili aplikacja
   będzie dostępna pod `https://twoja-nazwa.github.io/nazwa-repo/`.
4. Włącz uprawnienia do zapisu dla Actions: Settings → Actions → General →
   "Workflow permissions" → zaznacz **"Read and write permissions"** → Save.
   (Bez tego scraper nie będzie mógł commitować nowych danych.)
5. Odpal pierwszy scrape ręcznie: zakładka **Actions** → wybierz workflow
   "Update Senate transaction data" → **Run workflow**. Przy pierwszym
   uruchomieniu warto wpisać większą wartość w `lookback_days` (np. `400`),
   żeby dociągnąć więcej historii — kolejne, codzienne uruchomienia mogą
   zostać na domyślnych 14 dniach.

Od tego momentu workflow uruchamia się sam co 24h, dociąga nowe ujawnienia
i commituje je do `data/senate_transactions.json`. Aplikacja na GitHub Pages
wczytuje ten plik na żywo przy każdym otwarciu strony.

## Ważne zastrzeżenia

- To scraper prawdziwej, oficjalnej strony rządowej, nie oficjalne API.
  Jeśli Senat zmieni układ strony, selektory w `scrape_senate.py` może
  trzeba będzie poprawić — to normalna konserwacja, nie oznaka, że coś jest
  nie tak z pomysłem.
- Nie mogłem przetestować scrapera na żywo przeciw efdsearch.senate.gov z
  mojego środowiska (brak dostępu sieciowego do tej domeny w piaskownicy, w
  której to pisałem) — traktuj pierwsze uruchomienie jako test i sprawdź
  logi w zakładce Actions.
- Obejmuje tylko **Senat**. Izba Reprezentantów (House) publikuje część
  ujawnień jako skany PDF, co wymaga OCR — to sensowne rozszerzenie na
  później, ale nie jest tu zaimplementowane.
- Dane są publiczne i darmowe z mocy prawa (STOCK Act) — to narzędzie
  transparentności obywatelskiej, nie porada inwestycyjna.
