# Jadłospis EduPage (kalendarz)

Niestandardowa integracja Home Assistant do **publicznego** jadłospisu szkolnego EduPage (bez logowania).

Ostatni test na Home Assistant **2026.11.1**. W HACS minimum **2023.8.0**; starsze wersje mogą działać, ale nie są rutynowo sprawdzane.

[English](README.md)

## Instalacja

### HACS (zalecane)

1. Zainstaluj [HACS](https://hacs.xyz/docs/setup/download), jeśli go nie masz.
2. Dodaj to repozytorium jako [repozytorium niestandardowe](https://hacs.xyz/docs/faq/custom_repositories/) (kategoria: **Integracja**).
3. W HACS → Integracje zainstaluj **EduPage Menu Calendar**.
4. Uruchom ponownie Home Assistant.

[![Otwórz instancję HA i repozytorium w HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Flower7C3&repository=homeassistant-edupage-menu&category=integration)

### Ręcznie

Skopiuj katalog `custom_components/edupage_menu` do `config/custom_components/` w konfiguracji HA i zrestartuj system.

## Konfiguracja

**Ustawienia → Urządzenia i usługi → Dodaj integrację** → *EduPage Menu Calendar*.

Podaj publiczny adres strony jadłospisu (strona **menu** EduPage, np. `https://szkola.example/menu/`).

W opcjach integracji ustawisz m.in. odświeżanie, zakres tygodni (`weeks_range`, domyślnie `1-4`), dzień tygodnia w tytułach i zachowanie sensora „dzisiaj”.

## Karta Lovelace

Integracja rejestruje kartę `custom:edupage-menu-day` (zasób JS: `/edupage_menu/`).

```yaml
type: custom:edupage-menu-day
select_entity: select.jadlospis_wybor_dnia
sensor_entity: sensor.jadlospis_menu_wybrana_data
picker_arrows: true
picker_today: true
````

Przykłady: `custom_components/edupage_menu/examples/lovelace_jadlospis_dnia.yaml`.

## Encje

| Encja | Opis |
|--------|------|
| `select.*` | Wybór dnia |
| `sensor.*` (wybrana data) | Menu dla wybranego dnia |
| `sensor.*` (dzisiaj) | Menu na dziś |
| `sensor.*` (następny dzień) | Następny dzień szkolny (weekend → poniedziałek) |
| `calendar.*` | Kalendarz |

## Licencja

[MIT](LICENSE)