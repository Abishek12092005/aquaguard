import { useCallback, useEffect, useRef, useState } from 'react'

import { locationApi } from '@/api'
import Badge from '@/components/Badge'
import Button from '@/components/Button'
import Card from '@/components/Card'
import Icon from '@/components/Icon'
import LocationMapPicker from '@/components/LocationMapPicker'
import LocationSuggestions from '@/components/LocationSuggestions'
import LocationPinIcon from '@/components/LocationPinIcon'
import PageHeader from '@/components/PageHeader'
import Spinner from '@/components/Spinner'
import { ICONS } from '@/config/navigation'
import useDeviceArea from '@/hooks/useDeviceArea'
import useDeviceLocation from '@/context/useDeviceLocation'
import { errorMessage, formatDate, formatNumber } from '@/utils/format'

/**
 * Rainy Alerts — live rain warnings for the STATE this device is in.
 *
 * THE QUESTION THIS ANSWERS is "is it raining where I am, and should I expect
 * it to?", which is not the question Location Prediction answers. That screen
 * identifies a water SOURCE from a place the visitor chooses; this one reads
 * the device's OWN position and reports the weather. They are separate screens
 * because they need different things from the visitor and answer different
 * questions, which is also why the rain block was removed from Location
 * Prediction.
 *
 * WHERE THE NUMBERS COME FROM, and what is NOT done here:
 *
 *   * The browser supplies ONLY a latitude and longitude, and only after the
 *     visitor grants the geolocation permission. No position is defaulted,
 *     remembered between visits, or inferred.
 *   * The SERVER resolves that point to a place, reads the STATE out of it,
 *     resolves that state's administrative centre BY NAME, and takes a live
 *     forecast there. So the alert is about a region, not about one doorstep,
 *     and it is correct for every state - none is named or assumed in this
 *     file or in the code behind it.
 *   * Every figure shown is a number the weather service returned. Nothing is
 *     estimated, seasonal, rounded up for effect, or filled in when the service
 *     is unreachable. When the service cannot answer, this page says so and
 *     shows no figures at all, which is the only honest alternative to
 *     inventing them.
 *
 * THE EXACT COORDINATES ARE NEVER SHOWN. The place, the district and the state
 * are; a latitude and longitude would put a person's precise position on screen,
 * and the state name is both safer and the more useful answer for a rain
 * warning.
 *
 * PERMISSION IS AN OFFER, NOT A DEMAND. The page opens on an explanation and a
 * single button, and the browser's own prompt appears only when that button is
 * pressed. Asking on load would show a permission bar to someone who may not
 * want their position at all - and on some browsers that is an immediate
 * rejection the visitor never had the chance to understand. A refusal gets its
 * own message naming the browser setting to change, because "denied" on its own
 * tells the visitor nothing they can act on.
 */

export default function RainyAlerts() {
  // 'intro'   waiting for the visitor to choose
  // 'locating' asking the browser
  // 'loading'  coordinates in hand, forecast in flight
  // 'ready'    real data on screen
  // 'denied'   permission refused
  // 'unsupported' the browser has no geolocation at all
  // 'error'    something failed; the reason is shown
  const [stage, setStage] = useState('intro')
  // Whether the browser geolocation request started by "Allow" is still in
  // flight. The modal stays open with a spinner until the browser actually
  // returns a fix or an error - permission is never treated as granted early.
  const [requesting, setRequesting] = useState(false)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const attempt = useRef(0)

  /* ---------------------------------------------------------------------- */
  /* STEP 33: WHICH LOCATION THIS SCREEN IS ABOUT                             */
  /* ---------------------------------------------------------------------- */

  /**
   * `origin` records HOW the coordinates on screen were chosen, and it is the
   * only thing that tells the three workflows apart on the page. Nothing about
   * the workflow is implied by the coordinates themselves — a device fix, a
   * typed name and a dropped pin are all just a lat/lon — so the header states
   * which one produced the answer rather than presenting all three as if they
   * were the same thing.
   */
  const [origin, setOrigin] = useState(null) // 'device' | 'search' | 'map'
  /**
   * The place the current coordinates resolved to by name, for the two manual
   * workflows.
   *
   * The rain endpoint resolves its own region from the point, so this is NOT
   * how the forecast is fetched — it is what the header prints, because a
   * warning about "Unknown state" is unreadable when the user just carefully
   * picked the place on a map. It is `null` when the geocoder cannot name the
   * point, and the header then says exactly that instead of substituting the
   * name of the nearest town.
   */
  const [pickedPlace, setPickedPlace] = useState(null)
  // The coordinates every manual path resolves against, kept so "Check again"
  // re-reads the SAME place rather than silently re-running the device fix on a
  // page the visitor is already using a pin on.
  const [manualCoords, setManualCoords] = useState(null)
  // THE COORDINATES THE FORECAST ON SCREEN WAS ACTUALLY READ AT.
  //
  // Kept for the regional-alerts request below, which must ask about the SAME
  // point as the forecast above it. `manualCoords` only covers manual picks, so
  // it is null after a device fix; this carries all three paths (device, search,
  // map) and is what stops the regional section from falling back to a
  // state-wide, list-order sample that reads identically for every place in the
  // state.
  const [resolvedCoords, setResolvedCoords] = useState(null)
  // Guards the reverse lookup above against a slow earlier answer landing after
  // a newer location has been chosen.
  const placeRequestId = useRef(0)

  // The map popup: open state, the pin it was last given, and the reason a
  // confirmed pin was refused. STEP 26's contract from Location Prediction is
  // reused verbatim — a refusal keeps the map, the pin and the zoom on screen.
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerError, setPickerError] = useState(null)

  /* ---------------------------------------------------------------------- */
  /* STEP 33: SEARCH, AS A SECOND WAY IN                                     */
  /* ---------------------------------------------------------------------- */

  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState([])
  const [suggestionsOpen, setSuggestionsOpen] = useState(false)
  const [suggestionsLoading, setSuggestionsLoading] = useState(false)
  const [suggestionsError, setSuggestionsError] = useState(null)
  // Which row the keyboard is on. -1 is "no row chosen", which is NOT the same
  // as 0: pressing Enter with nothing highlighted must never silently move the
  // forecast to whichever match happened to rank first.
  const [activeIndex, setActiveIndex] = useState(-1)
  const optionRefs = useRef([])
  const suggestionRequestId = useRef(0)
  // The search field itself, for the shared suggestion portal's positioning.
  const inputRef = useRef(null)

  // The device's own administrative area, used ONLY to rank the autocomplete —
  // it is a preference, never a filter, and its absence (permission refused) is
  // a supported outcome that leaves the search behaving exactly as it always
  // has. Read inside the debounce timer from a ref, so resolving the area
  // mid-typing never restarts the lookup the user is waiting on.
  const deviceArea = useDeviceArea()
  const deviceAreaRef = useRef({ state: null, district: null })
  const [areaEpoch, setAreaEpoch] = useState(0)
  useEffect(() => {
    if (areaEpoch > 0 || !deviceArea.state) return
    deviceAreaRef.current = { state: deviceArea.state, district: deviceArea.district }
    setAreaEpoch((n) => n + 1)
  }, [deviceArea.state, deviceArea.district, areaEpoch])

  useEffect(() => {
    setActiveIndex(-1)
    optionRefs.current = []
  }, [suggestions])

  useEffect(() => {
    if (activeIndex < 0) return
    optionRefs.current[activeIndex]?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  // Debounced autocomplete through the SAME `locationApi.search` every other
  // screen uses, so a place typed here is the same place the Location Prediction
  // screen would have found — same rows, same ranking, same branch handling.
  useEffect(() => {
    const text = query.trim()
    ++suggestionRequestId.current
    const id = suggestionRequestId.current
    if (text.length < 1) {
      setSuggestions([])
      setSuggestionsLoading(false)
      setSuggestionsOpen(false)
      setSuggestionsError(null)
      return undefined
    }
    setSuggestionsLoading(true)
    setSuggestionsOpen(true)
    const area = deviceAreaRef.current
    const timer = setTimeout(async () => {
      try {
        const response = await locationApi.search({
          q: text,
          limit: 8,
          autocomplete: true,
          ...(area.state ? { state: area.state } : null),
          ...(area.district ? { district: area.district } : null),
        })
        if (id !== suggestionRequestId.current) return
        setSuggestions(Array.isArray(response.data) ? response.data : [])
        setSuggestionsError(null)
      } catch (err) {
        if (id !== suggestionRequestId.current) return
        // A failed lookup shows NOTHING rather than a stale list, which would be
        // presented as if it matched what is now in the box.
        setSuggestions([])
        setSuggestionsError(
          err?.isNetworkError || err?.isTimeout
            ? 'Could not reach the search service. Check your connection.'
            : 'Location search is unavailable right now. Please try again.',
        )
      } finally {
        if (id === suggestionRequestId.current) setSuggestionsLoading(false)
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [query, areaEpoch])

  /**
   * STEP 33: THE RAIN LOOKUP ITSELF, FOR ANY COORDINATES.
   *
   * ONE function, three callers — the device fix, a searched place and a
   * confirmed pin. They differ only in where the coordinates come from and in
   * the label the header prints; the request, the error handling and the
   * request-id guard are identical, which is what guarantees the three paths
   * cannot disagree about what the weather service said.
   *
   * The coordinates are handed to the rain endpoint EXACTLY as given. The server
   * resolves the region from them, so no state is named, assumed or defaulted
   * anywhere in this screen.
   */
  const loadRain = useCallback(async (coords, nextOrigin) => {
    const id = ++attempt.current
    setStage('loading')
    setError(null)
    setRefreshing(false)
    setOrigin(nextOrigin)
    // The point this forecast is being read at, remembered so the regional
    // section below asks about the SAME place instead of the whole state. Set
    // here (the one funnel every path shares) rather than in each caller, so the
    // device, search and map workflows cannot drift apart.
    setResolvedCoords({ lat: coords.lat, lon: coords.lon })
    try {
      const response = await locationApi.rainAlert({ lat: coords.lat, lon: coords.lon })
      // A slower earlier request must not overwrite a newer answer.
      if (id !== attempt.current) return
      setData(response.data)
      setStage('ready')
    } catch (err) {
      if (id !== attempt.current) return
      setError(
        errorMessage(
          err,
          'The rain service could not be reached. No forecast is shown rather than an invented one.',
        ),
      )
      setStage('error')
    }
  }, [])

  /**
   * STEP 33: A COORDINATE THE USER CHOSE, NAMED BEFORE IT IS USED.
   *
   * The rain lookup does not need the name, but the page does: without it the
   * header would print the region's name alone and the visitor would have no way
   * of telling whether the warning is about the place they just typed or about
   * somewhere else entirely.
   *
   * A NAME IS A DISPLAY VALUE, NOT A CONDITION ON SHOWING WEATHER. If the
   * reverse lookup fails the forecast is still loaded and the header says the
   * point could not be named - dropping a real weather answer because one
   * address lookup was slow would be trading a correct report for a cosmetic
   * one.
   */
  const commitCoords = useCallback(
    async (coords, nextOrigin) => {
      setManualCoords({ lat: coords.lat, lon: coords.lon })
      setPickedPlace(null)
      // A COUNTER OF ITS OWN, not `attempt`. `attempt` is incremented by the
      // forecast request that follows, so reusing it would guarantee the name
      // arrived after the counter moved and be discarded every time.
      const id = ++placeRequestId.current
      locationApi
        .reverse({ lat: coords.lat, lon: coords.lon })
        .then((response) => {
          if (id !== placeRequestId.current) return
          setPickedPlace(response.data ?? null)
        })
        .catch(() => {
          /* Stays null; the header reports the point as unnamed. */
        })
      await loadRain(coords, nextOrigin)
    },
    [loadRain],
  )

  /**
   * STEP 33: THE USER PICKED A PLACE FROM THE SEARCH.
   *
   * The whole geocoder result is reused AS-IS — its own coordinates, never a
   * re-resolve of the label. Re-resolving the same text is how a page ends up
   * reporting a warning for a different place than the one that was picked.
   */
  function chooseSuggestion(candidate) {
    const lat = Number(candidate.lat)
    const lon = Number(candidate.lon)
    setActiveIndex(-1)
    setSuggestions([])
    setSuggestionsOpen(false)
    setSuggestionsError(null)
    setQuery(candidate.branch_label || candidate.label || candidate.display_name || candidate.name || '')
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      setError('That search result carried no coordinates, so it cannot be used for a forecast.')
      setStage('error')
      return
    }
    commitCoords({ lat, lon }, 'search')
  }

  /**
   * STEP 33: ENTER INSIDE THE SEARCH FIELD.
   *
   * Four outcomes, and the ambiguity case is the one that matters: several
   * matching places means NONE is chosen. The list opens on the first row and
   * says how many places matched, because silently taking the top hit is how a
   * forecast gets attributed to a place the visitor never selected.
   */
  function handleSearchKeyDown(event) {
    const key = event.key
    if (key === 'ArrowDown' || key === 'ArrowUp') {
      if (suggestions.length === 0) return
      event.preventDefault()
      setSuggestionsOpen(true)
      setActiveIndex((current) => {
        const next = current + (key === 'ArrowDown' ? 1 : -1)
        if (next < 0) return suggestions.length - 1
        if (next >= suggestions.length) return 0
        return next
      })
      return
    }
    if (key === 'Escape') {
      if (!suggestionsOpen) return
      event.preventDefault()
      event.stopPropagation()
      setSuggestionsOpen(false)
      setActiveIndex(-1)
      return
    }
    if (key !== 'Enter') return

    // `preventDefault` FIRST and unconditionally. The field is not inside a
    // form today, and that is not a guarantee anyone can rely on later: an Enter
    // that reached a surrounding form would submit whatever that form does.
    event.preventDefault()

    if (activeIndex >= 0 && suggestions[activeIndex]) {
      chooseSuggestion(suggestions[activeIndex])
      return
    }
    if (suggestionsLoading) {
      setSuggestionsOpen(true)
      return
    }
    if (suggestions.length === 1) {
      chooseSuggestion(suggestions[0])
      return
    }
    if (suggestions.length > 1) {
      setSuggestionsOpen(true)
      setActiveIndex(0)
      return
    }
    setSuggestionsOpen(true)
  }

  // The app-wide location grant. Used to reuse a fix the shell already obtained
  // (so "Use my location" here does not fire a second browser request), to hand
  // a fix back with `reuseFix`, and to raise the permission popup on an explicit
  // click. It is never read to auto-run a forecast, because this page answers for
  // the place the visitor CHOOSES.
  const sharedLocation = useDeviceLocation()

  /** Ask for the position, then load the forecast for the state it falls in. */
  const detect = useCallback(async () => {
    // SECURE CONTEXT FIRST. `getCurrentPosition` silently no-ops on plain HTTP in
    // most browsers - no callback ever fires - so that is answered honestly
    // BEFORE the prompt is raised or a request is made, instead of leaving the
    // visitor on a spinner that will never stop.
    if (window.isSecureContext === false) {
      setStage('error')
      setError(
        'This page is not loaded over a secure connection (HTTPS), and browsers refuse to share a location over insecure origins. Open AquaGuard AI over HTTPS, or use the search box above to name a place instead.',
      )
      return
    }
    if (!('geolocation' in navigator)) {
      setStage('unsupported')
      return
    }

    // A FIX IS ALREADY IN HAND. Reuse it - the shell's Allow popup or the map's
    // own centring may have just obtained one - so this does not fire a second
    // browser request (or a second prompt) for the position it already has.
    const sharedFix = sharedLocation?.coords
    if (sharedFix && typeof sharedFix.lat === 'number' && typeof sharedFix.lon === 'number') {
      setPickedPlace(null)
      setManualCoords(null)
      await loadRain({ lat: sharedFix.lat, lon: sharedFix.lon }, 'device')
      return
    }

    // THE PERMISSION POPUP IS RAISED HERE, ON AN EXPLICIT CLICK.
    // A visitor who declined the first popup can still grant permission now, so
    // the prompt is re-offered rather than left permanently closed. Once granted,
    // `requestPermissionPrompt` returns false and the fix below runs directly.
    sharedLocation?.requestPermissionPrompt?.()

    const id = ++attempt.current
    setStage('locating')
    setRequesting(true)
    setError(null)
    setRefreshing(false)

    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const { latitude, longitude } = position.coords
        if (id !== attempt.current) return
        setRequesting(false)
        setPickedPlace(null)
        setManualCoords(null)
        // Hand the fix to the shared state (coordinates first, address in the
        // background) so a map marker or another screen reading it moves as soon
        // as a position exists.
        sharedLocation?.reuseFix?.({ lat: latitude, lon: longitude })
        await loadRain({ lat: latitude, lon: longitude }, 'device')
      },
      (geoError) => {
        if (id !== attempt.current) return
        setRequesting(false)
        if (geoError?.code === geoError?.PERMISSION_DENIED) {
          setStage('denied')
          return
        }
        if (geoError?.code === geoError?.TIMEOUT) {
          setStage('error')
          setError(
            'Finding your location took too long. This usually means the device could not get a fix — try again outdoors, or on a device with location services switched on, or search for a place above.',
          )
        } else {
          setStage('error')
          setError(
            'Your location is not available right now. Check that location services are switched on for this device, then try again — or search for a place above.',
          )
        }
      },
      { enableHighAccuracy: true,
        timeout: 15000,
        // A fix up to a minute old is fine for a rain warning, and reusing one
        // means opening the page a second time does not re-prompt the browser.
        maximumAge: 60000,
      },
    )
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  // Abandon an in-flight lookup when the page goes away, so a late answer cannot
  // set state on an unmounted component.
  useEffect(() => () => {
    attempt.current += 1
  }, [])

  /* ---------------------------------------------------------------------- */
  /* THIS PAGE WORKS FROM INPUT THE VISITOR GIVES IT, AND NOTHING ELSE       */
  /* ---------------------------------------------------------------------- */

  /**
   * NOTHING HERE READS THE DEVICE'S LOCATION ON ITS OWN.
   *
   * The page used to auto-run a forecast the moment the global popup's location
   * grant existed, which meant a screen that is supposed to answer for the place
   * the visitor CHOOSES silently answered for a GPS reading instead — and the two
   * could disagree with whatever they had typed or pinned. The brief is explicit:
   * the weather here is produced from user input.
   *
   * So the grant is not consulted. A forecast is loaded only when the visitor
   * does one of the two deliberate things this page offers - chooses a searched
   * place, or drops a pin on the map - or presses "Use my location" in the intro,
   * which is itself an explicit request in the same place a search would be.
   *
   * The permission popup is therefore about the browser's permission ALONE and
   * changes nothing on this screen.
   */

  useEffect(() => {
    // STEP 33: THE CONFIRMED POINT PUTS ITS OWN NAME IN THE BOX.
    //
    // Driven from `pickedPlace` rather than written at the moment of
    // confirmation, because the confirmation only knows coordinates - the name
    // arrives from the reverse lookup a moment later. Writing it in the handler
    // would put whatever happened to be in the box before that lookup landed,
    // which is how a confirmed pin ends up labelled with the place the visitor
    // had been looking at before they moved it.
    if (origin !== 'map' || !pickedPlace) return
    const name =
      pickedPlace.display_name ||
      [pickedPlace.city || pickedPlace.name, pickedPlace.district, pickedPlace.state]
        .filter(Boolean)
        .join(', ')
    if (name) setQuery(name)
  }, [origin, pickedPlace])

  /**
   * STEP 33: "CHECK AGAIN" RE-READS THE LOCATION ON SCREEN.
   *
   * Re-running the device fix unconditionally would be wrong for the two
   * manual workflows: the visitor who pinned a location on purpose would have
   * that choice silently replaced by a GPS reading they never asked for, on a
   * page whose entire purpose is reporting on the place they picked. So the
   * button refreshes whichever location is actually on screen, and falls back to
   * the device only when there is nothing else to refresh.
   */
  function refresh() {
    setRefreshing(true)
    if (manualCoords) {
      commitCoords(manualCoords, origin === 'search' ? 'search' : 'map')
      return
    }
    detect()
  }

  const weather = data?.weather

  // PROMPT 2, B.7: REGIONAL ALERTS for the resolved state. Loaded once the
  // state is known - after either a device fix, a search or a map pick has
  // answered - and independently of the main forecast, so a failure in one
  // never blanks the other. Held separately with its own request-id guard so a
  // slow earlier load cannot overwrite a newer one.
  const [regional, setRegional] = useState(null)
  const [regionalStatus, setRegionalStatus] = useState('idle') // idle | loading | ready | error
  const regionalRequestId = useRef(0)

  const stateName = data?.state || pickedPlace?.state || null
  // The exact point the forecast above was read at. Sent with the state so the
  // backend samples the districts NEAREST this location; without it every place
  // in a state got the same list-order sample and therefore the same numbers.
  const regionalLat = resolvedCoords?.lat
  const regionalLon = resolvedCoords?.lon
  useEffect(() => {
    if (!stateName) {
      setRegional(null)
      setRegionalStatus('idle')
      return
    }
    const id = ++regionalRequestId.current
    setRegionalStatus('loading')
    locationApi
      .regionalAlerts({ state: stateName, lat: regionalLat, lon: regionalLon })
      .then((response) => {
        if (id !== regionalRequestId.current) return
        setRegional(response.data ?? null)
        setRegionalStatus('ready')
      })
      .catch(() => {
        if (id !== regionalRequestId.current) return
        setRegional(null)
        setRegionalStatus('error')
      })
    return () => {
      regionalRequestId.current += 1
    }
  }, [stateName, regionalLat, regionalLon])

  /**
   * STEP 33: "NO ACTIVE ALERT" IS NOT "NO DATA".
   *
   * Two failures that look identical in a weather response and mean opposite
   * things, and the brief asks for them to be distinguishable:
   *
   *   * the provider answered and reported no warning  -> a real, reassuring
   *     answer, and the page says so explicitly rather than showing nothing;
   *   * the provider could not be reached at all     -> an outage, a rate limit
   *     or a rejected key, and the page says THAT instead.
   *
   * The test is whether a forecast actually came back. `data` exists only after
   * a successful response, so a null `weather` alongside a present `data` means
   * the request succeeded but carried nothing to display.
   */
  const providerUnavailable = stage === 'ready' && !weather

  return (
    <div>
      <PageHeader
        breadcrumb="Rainy Alerts"
        title="Rainy Alerts"
        description="Live rain warnings for wherever this device is, or for a place you search or pin on the map"
        actions={
          stage === 'ready' && (
            <Button onClick={refresh} disabled={refreshing}>
              {refreshing ? 'Updating…' : 'Check again'}
            </Button>
          )
        }
      />

      {/* STEP 33: THREE WAYS TO CHOOSE A LOCATION, ALWAYS REACHABLE.

          The search box and the map button sit ABOVE every stage panel, so a
          visitor whose location permission was refused - or who never wanted to
          grant it - is not stuck behind a refusal message with no way forward.
          Both manual paths are available from the first paint; only "Use my
          location" asks the browser for anything. */}
      <LocationChooser
        inputRef={inputRef}
        query={query}
        onQueryChange={(value) => {
          setQuery(value)
          setActiveIndex(-1)
        }}
        suggestions={suggestions}
        suggestionsOpen={suggestionsOpen}
        suggestionsLoading={suggestionsLoading}
        suggestionsError={suggestionsError}
        activeIndex={activeIndex}
        optionRefs={optionRefs}
        onOpenSuggestions={() => setSuggestionsOpen(true)}
        onCloseSuggestions={() => setSuggestionsOpen(false)}
        onHighlight={(index) => setActiveIndex(index)}
        onChoose={chooseSuggestion}
        onKeyDown={handleSearchKeyDown}
        onSearch={() => handleSearchKeyDown({ key: 'Enter', preventDefault() {} })}
        onPickOnMap={() => {
          setPickerError(null)
          setPickerOpen(true)
        }}
      />

      {/* NO SECOND PERMISSION POPUP.

          This used to render `RainPermissionModal` — a page-level blocking
          dialog — while the visitor had not yet answered. That was correct when
          this page owned the permission question, but the question is now asked
          ONCE by the GLOBAL popup mounted in the app shell
          (LocationPermissionPrompt). Leaving the modal here meant two
          permission dialogs could appear at the same time — the global one on
          top of this one — which is exactly the "multiple location permission
          popups" the brief forbids, and it also hid the page behind a dialog
          the visitor had already been asked.

          So the intro stage is now an ordinary INLINE CARD: it offers the same
          "Use my location" action, styled as page content rather than as a
          modal, and the only blocking popup in the application remains the one
          global prompt. A visitor who declined there still gets this card, can
          still press the button, and can always fall back to the search box and
          the map above it. */}
      {stage === 'intro' && (
        <Card className="mb-6">
          <div className="flex items-start gap-3">
            <span
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-aqua-50 text-aqua-600 dark:bg-aqua-900 dark:text-aqua-300"
              aria-hidden="true"
            >
              <LocationPinIcon className="h-5 w-5" animated={false} />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-base font-semibold tracking-tight text-slate-900 dark:text-white">
                Choose a location for rain alerts
              </h2>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                Search for a place by name above, or drop a pin on the map, and
                the forecast is read for that spot — nothing is looked up on its
                own. You can also use this device&rsquo;s location instead; your
                browser will ask for permission first, and the position is never
                stored.
              </p>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Button type="button" onClick={detect} loading={requesting}>
                  Use my location
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setStage('denied')}
                  disabled={requesting}
                >
                  I&rsquo;ll search instead
                </Button>
              </div>
            </div>
          </div>
        </Card>
      )}

      {stage === 'locating' && (
        <Card className="mb-6">
          <Spinner label="Asking your browser for this device's location…" />
        </Card>
      )}

      {stage === 'loading' && (
        <Card>
          <Spinner label="Looking up the rain forecast for your state…" />
        </Card>
      )}

      {stage === 'denied' && (
        <PermissionCard onRetry={detect} />
      )}

      {stage === 'unsupported' && (
        <Card>
          <Notice
            tone="caution"
            title="This browser cannot share a location"
            body="Geolocation is not available here, so the “Use my location” button cannot work. That does not stop you checking the rain — search for a place by name above, or open the map and drop a pin anywhere, and the forecast will be read for that spot instead."
          />
        </Card>
      )}

      {stage === 'error' && (
        <Card>
          <Notice
            tone="caution"
            title="The rain forecast is not available"
            body={error}
            onRetry={refresh}
          />
        </Card>
      )}

      {/* STEP 33: THE PROVIDER ANSWERED, AND ANSWERED WITH NOTHING.

          A successful response carrying no usable weather is not a crash and not
          a clean "all clear": it means the service was reached but returned
          nothing this page can report. It is stated as exactly that, and no
          figure is shown in its place. */}
      {providerUnavailable && (
        <Card>
          <Notice
            tone="caution"
            title="Weather data unavailable for this location"
            body={`The weather service was reached but returned no usable forecast for ${
              pickedPlace?.display_name || pickedPlace?.name || 'the point you selected'
            }. No rainfall figures are shown rather than invented ones. The service may be degraded, or the point may be outside the area it covers — try another place, or press “Check again”.`}
            onRetry={refresh}
          />
        </Card>
      )}

      {stage === 'ready' && data && weather && (
        <>
          <WhereAmI data={data} origin={origin} place={pickedPlace} />
          <RainStatus weather={weather} />
          <HeavyRainNotice weather={weather} />
          <DailyForecast weather={weather} />
        </>
      )}

      {/* PROMPT 2, B.7-B.9: REGIONAL ALERTS, at the bottom of the page.

          Rendered only when a state is resolved. The three states the brief
          requires are kept distinct:

            * rows with available=true   - real per-district forecasts
            * zero rows with available=true  - "Alert data unavailable" (an
              outage, NOT an all-clear)
            * rows all with available=false and reason=not_locatable — data is
              available but no district could be placed, said as such */}
      {regionalStatus !== 'idle' && stateName && (
        <RegionalAlerts
          status={regionalStatus}
          regional={regional}
          stateName={stateName}
        />
      )}

      {/* STEP 33: THE MAP POPUP, REUSED EXACTLY AS LOCATION PREDICTION USES IT.

          The same `LocationMapPicker`, with the same search, the same pin
          dragging and the same "Use This Location" action - so a place is chosen
          the same way on both screens and there is no second, subtly different
          map picker to keep working.

          `reverse` is not passed: the picker only reverse-geocodes the pin for
          display when a function is supplied, and this page names the point
          itself once the visitor confirms, from the same endpoint. The
          `manualCoords` passed as `initial` means reopening the map returns to
          the last confirmed pin rather than a world view the visitor has to pan
          back from. */}
      <LocationMapPicker
        open={pickerOpen}
        initial={manualCoords ?? undefined}
        mode="manual"
        error={pickerError}
        onMoved={() => setPickerError(null)}
        busy={stage === 'loading'}
        onClose={() => {
          setPickerOpen(false)
          setPickerError(null)
        }}
        onConfirm={(coords) => {
          setPickerOpen(false)
          setPickerError(null)
          commitCoords(coords, 'map')
        }}
      />
    </div>
  )
}

/**
 * STEP 33: THE SECOND AND THIRD WAYS TO CHOOSE A LOCATION.
 *
 * A live-autocomplete search box and a button that opens the map popup, sitting
 * above everything on the page so they stay reachable whatever state the screen
 * is in - including the states where the device path has failed.
 *
 * The dropdown reuses the stacking rules fixed in Prompt 5, which is why its
 * wrapper is `z-20` and the list itself clears Leaflet's control layer: this
 * box sits directly above the map element in the DOM order, so anything less
 * would let the zoom buttons paint over the suggestions.
 */
function LocationChooser({
  inputRef,
  query,
  onQueryChange,
  suggestions,
  suggestionsOpen,
  suggestionsLoading,
  suggestionsError,
  activeIndex,
  optionRefs,
  onOpenSuggestions,
  onChoose,
  onKeyDown,
  onPickOnMap,
  onSearch,
  onCloseSuggestions,
  onHighlight,
}) {
  const open = suggestionsOpen && (suggestionsLoading || suggestionsError || suggestions.length > 0)

  return (
    <Card className="mb-6" title="Choose a location" subtitle="Search by name, or drop a pin on the map">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
        {/* `relative z-20` gives the list a stacking context of its own, above
            the map below it; the list then clears Leaflet's control layer. */}
        <div className="relative z-20 min-w-0 flex-1">
          <span
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
            aria-hidden="true"
          >
            <Icon path={ICONS.search} className="h-4 w-4" />
          </span>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            onKeyDown={onKeyDown}
            onFocus={onOpenSuggestions}
            className="input pl-9"
            placeholder="Search a city, town or landmark…"
            aria-label="Search for a location"
            autoComplete="off"
            role="combobox"
            aria-expanded={open}
            aria-controls="rain-suggestions"
            aria-autocomplete="list"
            aria-activedescendant={
              activeIndex >= 0 && suggestions[activeIndex]
                ? `rain-suggestion-${activeIndex}`
                : undefined
            }
            data-testid="rain-search"
          />

          {/* THE SAME SHARED SUGGESTION PANEL THE LOCATION PAGE USES.

              This list used to be an absolutely-positioned child of this
              wrapper, which sits inside a <Card> whose `overflow-hidden`
              clipped it at the card's bottom edge - a longer list simply
              vanished. The portal panel renders to <body>, keeps the ~190px
              scrollable height, dismisses on an outside press, and labels a
              chain's branches the same way the Location page does. The
              scroll-into-view effect above still works: the option rows keep
              the same ids, they just live in the portal now. */}
          <LocationSuggestions
            inputRef={inputRef}
            open={open && query.trim().length > 0}
            loading={suggestionsLoading}
            error={suggestionsError}
            suggestions={suggestions}
            activeIndex={activeIndex}
            onHighlight={onHighlight}
            onChoose={onChoose}
            onClose={onCloseSuggestions}
            listId="rain-suggestions"
            optionIdPrefix="rain-suggestion"
            testIdPrefix="rain-suggestion"
            optionRefs={optionRefs}
          />
        </div>

        <Button onClick={onPickOnMap} className="shrink-0 sm:mt-0">
          <Icon path={ICONS.analytics} className="h-4 w-4" />
          Pick on map
        </Button>

        {/* THE GO BUTTON. Visible, at the search row's right corner, for the
            user who does not know Enter works. It calls the SAME key handler the
            field uses, so the keyboard path and this button can never drift. */}
        <Button onClick={onSearch} className="shrink-0 sm:mt-0" aria-label="Search" data-testid="rain-search-go">
          <Icon path={ICONS.search} className="h-4 w-4" />
          Enter
        </Button>
      </div>

      <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
        The forecast is read for the place you choose. Nothing about your position is
        requested unless you press “Use my location”.
      </p>
    </Card>
  )
}

/* -------------------------------------------------------------------------- */
/* The opening screen                                                          */
/* -------------------------------------------------------------------------- */

/**
 * The refusal screen.
 *
 * A denial on its own is a dead end: "permission denied" tells the visitor
 * nothing they can act on. This names the setting each browser hides it behind,
 * because the permission is recoverable and the visitor is the only one who can
 * change it.
 *
 * STEP 33: IT IS NOT A DEAD END ANY MORE. It used to be the end of the screen —
 * every other panel was gated behind a successful device fix. The search box and
 * the map button sit above this card and work regardless, so the refusal now
 * reads as one closed door among two open ones rather than as the only exit.
 */
function PermissionCard({ onRetry }) {
  return (
    <Card className="mb-6">
      <Notice
        tone="caution"
        title="Rainy Alerts could not use your device’s location"
        body={`Your browser blocked the request to read this device’s position, so the “Use my location” route is unavailable.

You do not need it. Search for a place in the box above, or press “Pick on map” and confirm a pin — the forecast is then read for that spot, and everything on this page works exactly as it would have.

If you would rather use your position, allow it:
  • Chrome or Edge — click the icon at the right of the address bar, then set
    Location to “Allow”, and reload the page.
  • Firefox — click the padlock in the address bar, then clear “Block access to
    your location”.
  • Safari on iPhone or iPad — Settings › Safari › Location, then reload.`}
        onRetry={onRetry}
      />
    </Card>
  )
}

/* -------------------------------------------------------------------------- */
/* The answer                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * Which state the device turned out to be in.
 *
 * This is the whole premise of the screen stated plainly, and it names the
 * device's exact coordinates nowhere: the place, the district and the state are
 * shown, because a rain warning for a region is what is wanted and a latitude is
 * not. `forecast_at_state_centre` says where the figures were measured, which is
 * the state's administrative centre rather than the doorstep — a distinction
 * worth stating rather than hiding, since it is why the answer is regional.
 *
 * STEP 33: TWO LOCATIONS, NOT ONE, AND NEITHER IS ASSUMED.
 *
 * The card now answers "which place is this about?" for all three workflows, and
 * it never falls back to a default. The visitor's own place comes first when
 * there is one, because it is the point they actually chose; the region the
 * backend forecast for is shown beside it, clearly labelled as the region, and
 * `origin` states which of the three workflows produced the answer so a warning
 * is never attributed to the device when it was a typed place, or the reverse.
 *
 * NOTHING IS HARDCODED. There is no state named as a default anywhere in this
 * file: a request that names no region renders "Region not identified", which is
 * the honest reading of a response that identified none.
 */
function WhereAmI({ data, origin, place }) {
  const region = data.place || {}
  const chosen = place || null
  const regionArea = [region.city || region.name, region.district].filter(
    (part, index, all) => part && all.indexOf(part) === index,
  )
  const chosenLine = chosen
    ? [
        chosen.display_name ||
          [chosen.city || chosen.name, chosen.district, chosen.state].filter(Boolean).join(', '),
      ].filter(Boolean)
    : []

  const originText =
    origin === 'device'
      ? 'Detected from this device’s location'
      : origin === 'search'
        ? 'Chosen by searching for a place'
        : 'Chosen by dropping a pin on the map'

  return (
    <Card className="mb-6" title="Where this is about">
      <div className="flex items-start gap-4">
        <span
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-aqua-50 text-aqua-600 dark:bg-aqua-900 dark:text-aqua-300"
          aria-hidden="true"
        >
          <Icon path={ICONS.location} className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          {/* The place the visitor chose leads, because it is the one they are
              asking about. It is omitted entirely for a device fix, where there
              is no such choice to report. */}
          {chosenLine.length > 0 ? (
            <>
              <p className="text-lg font-semibold capitalize tracking-tight text-slate-900 dark:text-white">
                {chosenLine[0]}
              </p>
              {chosen.pincode && (
                <p className="mt-0.5 text-sm text-slate-600 dark:text-slate-300">
                  Pincode {chosen.pincode}
                </p>
              )}
            </>
          ) : origin !== 'device' ? (
            /* A manual point the geocoder could not name. Said plainly — the
               forecast below is still real and is still shown. */
            <p className="text-lg font-semibold tracking-tight text-slate-900 dark:text-white">
              The point you chose
            </p>
          ) : null}

          <p className="mt-0.5 text-sm text-slate-600 dark:text-slate-300">
            {data.label || data.state || 'Region not identified'}
            {regionArea.length > 0 ? ` · ${regionArea.join(', ')}` : ''}
          </p>

          <p className="mt-3 text-2xs text-slate-400 dark:text-slate-500">
            {originText}
            {data.country ? ` · ${data.country}` : ''}
            {data.forecast_at_state_centre
              ? ' · forecast taken at the region’s administrative centre'
              : ' · forecast taken at the chosen point'}
            {data.source ? ` · data from ${data.source}` : ''}
            {data.generated_at ? ` · checked ${formatDate(data.generated_at)}` : ''}
          </p>
        </div>
      </div>
    </Card>
  )
}

/**
 * Whether it is raining now, and whether it is coming.
 *
 * The three states come from the backend, which derives them from the service's
 * own current-precipitation and daily-sum figures. The wording here is chosen to
 * match the state rather than to sound alarming: an area with no rain in the next
 * two days is not being described as "flooded" or "at risk", because the numbers
 * do not say that.
 */
function RainStatus({ weather }) {
  if (!weather) return null
  const { status, current_mm: currentMm, soon_mm: soonMm } = weather
  const key = status?.key
  const raining = key === 'occurring'
  const soon = key === 'expected_soon'

  const headline = raining
    ? 'Rain is falling right now'
    : soon
      ? 'Rain is expected in the next day or two'
      : 'No significant rain expected'

  const detail = raining
    ? `About ${formatNumber(currentMm, 1)} mm has fallen in the current hour in this state.`
    : soon
      ? `About ${formatNumber(soonMm, 1)} mm is forecast over the next day or two.`
      : 'Neither the current hour nor the next two days show significant rainfall in this state.'

  return (
    // THE CURRENT-RAIN-STATUS CARD IS BLACK IN DARK MODE.
    //
    // `bg-black` + `dark:text-white` on the card itself, so the whole panel —
    // heading, subtitle and body — is black with white text, exactly as the
    // brief asks. The `!important`-free ordering works because these utilities
    // land on the same element the `.card` class styles, and Tailwind utilities
    // beat a component-layer class without needing specificity tricks.
    // Light mode is untouched: no `bg-*` is set for it, so `.card`'s existing
    // white/glass surface still applies.
    <Card
      className="mb-6 dark:bg-black dark:ring-slate-800 dark:text-white"
      title="Current rain status"
      subtitle={status?.label}
      aria-live="polite"
    >
      <div
        className={`flex items-start gap-3 rounded-card border px-4 py-3 ${raining || soon
            ? 'border-caution-light bg-caution-light/40 dark:border-slate-700 dark:bg-black'
            : 'border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-black'
          }`}
      >
        {/* AN SVG, NOT AN EMOJI. The OS-drawn weather emoji rendered as a
            different glyph on every platform and could not take the accent
            colour. This uses the app's own icon set, coloured to match the
            status: the amber caution tint while rain is falling or coming, and
            the aqua brand tint when it is clear. */}
        <span
          className={`mt-0.5 shrink-0 ${raining || soon
              ? 'text-caution-dark dark:text-caution-light'
              : 'text-aqua-600 dark:text-aqua-300'
            }`}
          aria-hidden="true"
        >
          <Icon
            path={
              raining
                ? 'M6 14a4 4 0 0 1 .6-8 5 5 0 0 1 9.4 1A3.5 3.5 0 0 1 18 14M8 18l-1 3M12 18l-1 3M16 18l-1 3'
                : soon
                  ? 'M6 13a4 4 0 0 1 .6-8 5 5 0 0 1 9.4 1A3.5 3.5 0 0 1 18 13M12 17v4M9 19l3 3 3-3'
                  : 'M7.5 19a4.5 4.5 0 0 1 .5-9 6 6 0 0 1 11 2.4A3.6 3.6 0 0 1 17 19Z'
            }
            className="h-7 w-7"
            strokeWidth={1.8}
          />
        </span>
        <div className="min-w-0">
          {/* THE HEADLINE KEEPS ITS CAUTION TINT, BUT ON A BLACK CARD.
              "Rain is expected in the next day or two" is the sentence the brief
              says to preserve, so its amber `caution-light` wording stays in dark
              mode — that tint is what makes the warning read as a warning, and it
              still clears contrast on black (the amber is far lighter than the
              surface). Only the surface changed, not the words or their colour. */}
          <p
            className={`text-sm font-semibold ${raining || soon
                ? 'text-caution-dark dark:text-caution-light'
                : 'text-slate-700 dark:text-white'
              }`}
          >
            {headline}
          </p>
          <p className="mt-0.5 text-sm text-slate-600 dark:text-slate-200">
            {detail}
          </p>
        </div>
      </div>
    </Card>
  )
}

/**
 * The heavy-rain warning, when the service's figures cross the threshold.
 *
 * SHOWN ONLY WHEN THE NUMBERS SAY SO. `weather.heavy` is the backend's
 * judgement from measured forecast values against the IMD heavy-rainfall
 * thresholds — never from the month, the place name, or a habit of what the
 * season is usually like.
 *
 * The sentence is the backend's, and it is deliberately careful: it says rain
 * MAY increase the possibility of contamination and runoff. It never says rain
 * makes water unsafe, because a rainfall forecast cannot establish that.
 */
function HeavyRainNotice({ weather }) {
  if (!weather?.heavy || !weather.message) return null
  const { heavy_day: heavyDay } = weather

  return (
    <Card className="mb-6">
      <div
        role="alert"
        className="flex items-start gap-3 rounded-card border-unsafe-light bg-unsafe-light/40 px-4 py-3 dark:border-slate-700 dark:bg-slate-900"
      >
        <span className="mt-0.5 shrink-0 text-unsafe-dark dark:text-unsafe-light" aria-hidden="true">
          <Icon path={ICONS.info} className="h-5 w-5" />
        </span>
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-sm font-semibold text-unsafe-dark dark:text-unsafe-light">
            {/* The warning glyph is the shared SVG icon, not the "⚠️" emoji. */}
            <Icon path={ICONS.alerts} className="h-4 w-4 shrink-0" />
            Heavy rain warning
          </p>
          <p className="mt-0.5 text-sm text-slate-600 dark:text-slate-300">
            {weather.message}
          </p>
          {heavyDay && (
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Forecast for {heavyDay.date}: about {formatNumber(heavyDay.mm, 1)} mm,
              which is above the heavy-rainfall threshold of{' '}
              {formatNumber(weather.thresholds?.daily_mm, 1)} mm a day.
            </p>
          )}
        </div>
      </div>
    </Card>
  )
}

/**
 * The near-term forecast, as the daily figures that produced the verdict above.
 *
 * Shown so the alert can be checked rather than taken on trust: every verdict on
 * this page is derived from these numbers, and a reader who can see them has no
 * reason to take the summary on trust alone.
 */
function DailyForecast({ weather }) {
  const days = weather?.days || []
  if (days.length === 0) return null
  const heavy = weather.thresholds?.daily_mm ?? 64.5

  return (
    <Card
      className="mb-6"
      title="Near-term forecast"
      subtitle={`Daily rainfall for the next ${Math.min(days.length, 7)} days`}
    >
      <ul className="space-y-1.5">
        {days.slice(0, 7).map((day) => (
          <li
            key={day.date}
            className="flex items-center justify-between gap-3 text-sm"
          >
            <span className="text-slate-600 dark:text-slate-300">
              {day.date}
              {day.mm >= heavy && (
                <span className="ml-2 text-2xs font-semibold uppercase tracking-wide text-unsafe-dark">
                  heavy
                </span>
              )}
            </span>
            <span
              className={`font-medium tabular ${day.mm >= heavy
                  ? 'text-unsafe-dark'
                  : 'text-slate-800 dark:text-slate-100'
                }`}
            >
              {formatNumber(day.mm, 1)} mm
            </span>
          </li>
        ))}
      </ul>
    </Card>
  )
}

/* -------------------------------------------------------------------------- */
/* Shared notice                                                               */
/* -------------------------------------------------------------------------- */

/** One honest failure message, with a retry when retrying could help. */
function Notice({ tone = 'caution', title, body, onRetry }) {
  return (
    <div
      role="alert"
      className={`flex items-start gap-3 rounded-card border px-4 py-4 ${tone === 'caution'
          ? 'border-caution-light bg-caution-light/40 dark:border-slate-700 dark:bg-slate-900'
          : 'border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-900'
        }`}
    >
      <span
        className={`mt-0.5 shrink-0 ${tone === 'caution' ? 'text-caution-dark dark:text-caution-light' : 'text-slate-500'
          }`}
        aria-hidden="true"
      >
        <Icon path={ICONS.info} className="h-5 w-5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-slate-900 dark:text-white">
          {title}
        </p>
        <div className="mt-1 whitespace-pre-line text-sm text-slate-600 dark:text-slate-300">
          {body}
        </div>
        {onRetry && (
          <div className="mt-3">
            <Button onClick={onRetry}>Try again</Button>
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * PROMPT 2, B.7-B.9: THE REGIONAL ALERTS SECTION, at the bottom of Rainy Alerts.
 *
 * Every row is a real forecast read at that district's own coordinates by the
 * server. The section distinguishes the two states the brief requires: "no
 * active alerts found" (the provider answered, and every district is quiet) is
 * a reassuring answer, while "Alert data unavailable" (the provider could not
 * be reached or could not place the districts) is a limitation, stated as one.
 */
function RegionalAlerts({ status, regional, stateName }) {
  if (status === 'loading') {
    return (
      <Card className="mt-6" title={`Rain alerts across ${stateName}`} aria-live="polite">
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-12 animate-pulse rounded-field bg-slate-100 dark:bg-slate-800" />
          ))}
        </div>
        <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
          Reading the current forecast for districts across the state…
        </p>
      </Card>
    )
  }

  if (status === 'error') {
    return (
      <Card className="mt-6" title={`Rain alerts across ${stateName}`}>
        <Notice
          tone="caution"
          title="Alert data unavailable"
          body="The weather service could not be reached for the regional outlook, so no district rows are shown rather than invented ones."
        />
      </Card>
    )
  }

  if (!regional) return null

  const rows = Array.isArray(regional.rows) ? regional.rows : []
  const available = rows.filter((row) => row.available)
  const notPlaced = rows.filter((row) => !row.available && row.reason === 'not_locatable')

  return (
    <Card
      className="mt-6"
      title={`Rain alerts across ${regional.label || stateName}`}
      subtitle={`Real forecasts, read at each district's own location · ${regional.source || 'Open-Meteo'}`}
    >
      {available.length === 0 ? (
        <Notice
          tone="caution"
          title="Alert data unavailable"
          body={`The weather service could not provide a reliable outlook for the districts of ${regional.label || stateName} right now. No alerts are shown rather than estimated ones — try again shortly.`}
        />
      ) : (
        <>
          {available.length === rows.length ? null : (
            <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">
              {notPlaced.length > 0
                ? `${notPlaced.length} district${notPlaced.length > 1 ? 's' : ''} could not be placed on the map and ${notPlaced.length > 1 ? 'are' : 'is'} omitted rather than guessed.`
                : `${rows.length - available.length} district${rows.length - available.length > 1 ? 's' : ''} had no reliable forecast and ${rows.length - available.length > 1 ? 'are' : 'is'} omitted.`}
            </p>
          )}
          <ul className="space-y-3" data-testid="regional-alerts">
            {available.map((row) => {
              const weather = row.weather || {}
              const statusKey = weather.status?.key || 'none'
              const tone =
                weather.heavy ? 'high'
                  : statusKey === 'occurring' ? 'moderate'
                    : statusKey === 'expected_soon' ? 'moderate'
                      : 'low'
              return (
                <li
                  key={row.name}
                  className="flex flex-wrap items-center gap-3 rounded-field border border-slate-100 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-800"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                      {row.name}
                      <span className="ml-2 text-xs font-normal text-slate-500 dark:text-slate-400">
                        {row.state}
                      </span>
                    </p>
                    <p className="mt-0.5 text-xs text-slate-600 dark:text-slate-300">
                      {weather.message ||
                        weather.status?.label ||
                        'No significant rain expected'}
                      {weather.raining_now && weather.current_mm != null && (
                        <span className="ml-2 text-slate-500 dark:text-slate-400">
                          {weather.current_mm} mm/h now
                        </span>
                      )}
                      {!weather.raining_now && weather.soon_mm > 0 && (
                        <span className="ml-2 text-slate-500 dark:text-slate-400">
                          {weather.soon_mm} mm expected in 48 h
                        </span>
                      )}
                    </p>
                  </div>
                  <Badge risk={tone} />
                  <span className="text-2xs text-slate-400 dark:text-slate-500">
                    Updated {formatDate(regional.generated_at)}
                  </span>
                </li>
              )
            })}
          </ul>
          {available.length > 0 && available.every((row) => (row.weather?.status?.key || 'none') === 'none' && !row.weather?.heavy) && (
            <p className="mt-3 text-xs font-medium text-safe-dark dark:text-safe-light" data-testid="no-active-alerts">
              No active alerts found across the districts sampled.
            </p>
          )}
        </>
      )}
    </Card>
  )
}
