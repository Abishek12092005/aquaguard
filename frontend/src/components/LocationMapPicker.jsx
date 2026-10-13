import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

import Button from '@/components/Button'
import Icon from '@/components/Icon'
import { ICONS } from '@/config/navigation'
import { locationApi } from '@/api'
import LocationSuggestions from '@/components/LocationSuggestions'
import useDeviceArea from '@/hooks/useDeviceArea'

/**
 * THE MAP'S TILE SOURCE, READ FROM THE ENVIRONMENT.
 *
 * When `VITE_GOOGLE_MAPS_API_KEY` is set, the map renders GOOGLE'S road map
 * through the Maps Raster Tiles endpoint of Google Maps Platform
 * (`maps.googleapis.com/maps/v1/maptile`) — the supported, key-scoped way to
 * draw Google map tiles on a custom canvas. The key travels only as a query
 * parameter on the tile requests Google itself serves; no server-side
 * credential is involved or exposed.
 *
 * IMPORTANT: this must be a BROWSER key restricted by HTTP referrer, created
 * in the Google Cloud console (Maps Raster Tiles API enabled). Anything
 * `VITE_`-prefixed is compiled into the bundle and is public by definition —
 * the referrer restriction is what protects it. Without the key the map falls
 * back to OpenStreetMap exactly as before, so the app keeps working with no
 * configuration at all.
 */
const GOOGLE_MAPS_KEY = (import.meta.env?.VITE_GOOGLE_MAPS_API_KEY || '').trim()
// Kept module-private: this file must export only components so React Fast
// Refresh stays correct, and nothing outside it needs to know which tiles are in
// use. `mapTileLayer` below is the reader.
const usingGoogleMaps = Boolean(GOOGLE_MAPS_KEY)

/** The tile layer for the current configuration. Google first, OSM fallback. */
function mapTileLayer() {
  if (usingGoogleMaps) {
    return {
      url: `https://maps.googleapis.com/maps/v1/maptile?x={x}&y={y}&z={z}&key=${GOOGLE_MAPS_KEY}`,
      options: { maxZoom: 20, attribution: '&copy; Google Maps' },
    }
  }
  return {
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    options: { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' },
  }
}

/**
 * Manual location selector — a REAL interactive map (Step 24).
 *
 * Opens a modal with a REAL interactive slippy map — GOOGLE Maps tiles when
 * `VITE_GOOGLE_MAPS_API_KEY` is configured, OpenStreetMap tiles otherwise. The
 * user can pan, zoom, tap to drop a pin and drag it to fine-tune; confirming
 * hands the chosen coordinates to the parent, which reverse-geocodes them on
 * the server — exactly the same validation path a search or "use my location"
 * uses.
 *
 * NO HARDCODED COORDINATES. With no previous selection the map is NOT opened
 * on a fixed city: the browser's geolocation centres it, and failing that it
 * opens on a plain world view with no pin until the user taps somewhere.
 *
 * STEP 25: the map also serves "Use My Location", which hands it a fix it
 * already holds. Two additions make that work:
 *
 *   1. `mode` tells the modal whether the pin is a DEVICE FIX or a MANUAL pick,
 *      which is not a cosmetic distinction - it decides what the confirm button
 *      is allowed to do and what the modal says about the point.
 *   2. `reverse` reverse-geocodes the pin IN THE MODAL as it moves, so the
 *      place name is on screen beside the map instead of only appearing after
 *      the modal closes. The server does the resolving, exactly as it does for
 *      every other path; the browser never decides what a point is called.
 */

/** The map marker. A Leaflet DivIcon (pure SVG) instead of the default PNG,
 * whose asset URLs break under bundlers. */
const PIN_ICON = L.divIcon({
  className: 'aquaguard-map-pin',
  html: `<span style="display:block;transform:translate(-50%,-100%)">
    <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#0e9de8" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round" style="filter:drop-shadow(0 2px 2px rgba(0,0,0,.35))">
      <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" fill="#0e9de8" fill-opacity="0.2"/>
      <circle cx="12" cy="10" r="3" fill="#0e9de8" stroke="none"/>
    </svg>
  </span>`,
  iconSize: [30, 30],
  iconAnchor: [15, 30],
})

/** Format a coordinate to 5 decimal places, the resolution of the pin. */
function round5(value) {
  return Math.round(value * 1e5) / 1e5
}

export default function LocationMapPicker({
  open,
  initial,
  onClose,
  onConfirm,
  busy = false,
  mode = 'manual',
  reverse = null,
  // STEP 26: why a confirmed pin was refused. Rendered INSIDE the modal so the
  // map, the pin and the zoom level all survive the failure.
  error = null,
  onMoved = null,
}) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  // STEP 26: `onMoved` in a ref, because the Leaflet handlers are registered once
  // when the map is created and would otherwise close over the first render's
  // prop - so a later callback would never be called.
  const onMovedRef = useRef(onMoved)
  useEffect(() => {
    onMovedRef.current = onMoved
  }, [onMoved])
  const markerRef = useRef(null)

  // The chosen point. Null until the user taps the map (or a previous
  // selection was handed in) — the map is never opened on an invented place.
  const [point, setPoint] = useState(null)
  // STEP 25: WHAT THE PIN ACTUALLY IS, resolved on the server as the pin moves.
  // `null` while it is in flight and whenever the geocoder cannot name the point
  // — the modal then says so rather than showing a stale or invented name.
  const [resolved, setResolved] = useState(null)
  const [resolving, setResolving] = useState(false)

  // --- STEP 27: SEARCH FROM INSIDE THE MAP ---------------------------------
  //
  // The same autocomplete Location Prediction uses, pointed at the same
  // provider (`locationApi.search`), so a place found here and a place found
  // there are the same place - same rows, same ranking, same branch handling.
  // It is deliberately NOT a second geocoder with its own idea of what matches.
  const [searchText, setSearchText] = useState('')
  const [suggestions, setSuggestions] = useState([])
  const [suggestionsOpen, setSuggestionsOpen] = useState(false)
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState(null)
  // The place the user last picked FROM THE SEARCH, as opposed to the place the
  // pin currently resolves to. The two differ whenever the pin has been moved
  // since, and the difference is what tells the panel which of the two it is
  // describing - without it, a dragged pin would still be labelled with the
  // search result the user has since moved away from.
  //
  // Only the setter is consumed (the pick handlers write it); the value itself
  // is read inside the pick handlers below, so the destructuring keeps the
  // tuple that `useState` returns without an unused binding.
  const [, setSearchPicked] = useState(null)
  // Guards against a slow earlier request overwriting a newer answer.
  const searchRequestId = useRef(0)
  // STEP 30: THE DEVICE'S OWN AREA, for ranking the suggestions.
  //
  // The same hook the page's own search uses, so a place found from inside the
  // map ranks identically to one found in the box above it - one ranking rule
  // for the whole application rather than two that can disagree. Resolving
  // geolocation here is safe because `useDeviceArea` guards itself against
  // re-prompting, and it degrades to "no preference" rather than to an error.
  const deviceArea = useDeviceArea()
  // In a ref, so the search effect does not re-run - and re-query - every time
  // the device area resolves while the user is part-way through typing.
  const deviceAreaRef = useRef(deviceArea)
  useEffect(() => {
    deviceAreaRef.current = deviceArea
  }, [deviceArea])
  // The debounce timer, so a pick can cancel a lookup that has not gone out yet.
  const pendingSearch = useRef(null)
  // STEP 27: THE TEXT IN THE BOX CAME FROM A PICK, NOT FROM TYPING.
  //
  // Selecting a suggestion writes the place's own label into the box. That is a
  // display value, not something the user asked to search for, so the effect that
  // searches on every change must not treat it as a new query. Without this flag
  // the flow visibly broke at its own end: the list was cleared, and the very
  // next render re-queried the full label and re-opened the dropdown on top of the
  // map the search had just moved. Typing clears the flag again, so the next
  // keystroke searches normally.
  const pickedRef = useRef(false)

  // --- STEP 31: KEYBOARD OWNERSHIP OF THE SUGGESTION LIST ------------------
  //
  // `activeIndex` is the row the keyboard is currently on, and -1 means "no row
  // chosen yet". It is deliberately NOT initialised to 0: pressing Enter with
  // nothing highlighted must not silently move the map to whichever row happens
  // to sort first when several places match.
  const [activeIndex, setActiveIndex] = useState(-1)
  // A message under the box explaining why Enter did nothing, for the case where
  // Enter was pressed with no usable suggestion (still searching, or none found).
  const [enterNotice, setEnterNotice] = useState(null)
  const inputRef = useRef(null)
  const optionRefs = useRef([])
  // Reset whenever the result set changes, so a highlight from a previous query
  // can never point at a row index that no longer exists.
  useEffect(() => {
    setActiveIndex(-1)
    optionRefs.current = []
  }, [suggestions])

  // Keep the highlighted row inside the scroll area of a long list.
  useEffect(() => {
    if (activeIndex < 0) return
    optionRefs.current[activeIndex]?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  /**
   * STEP 26: PLACE THE PIN AT THE CENTRE OF THE VIEW, BY KEYBOARD.
   *
   * With no pointer position to read, the centre of what the user is looking at
   * is the only point that can honestly be claimed - naming a coordinate the
   * user never indicated would be exactly the fabrication the brief forbids.
   * Declared out here so the JSX key handler can reach it.
   */
  function handleKeyAtCentre() {
    const map = mapRef.current
    if (!map) return
    const centre = map.getCenter()
    setPoint({ lat: round5(centre.lat), lon: round5(centre.lng) })
    placeMarker(map, centre.lat, centre.lng)
    setSearchPicked(null)
    onMovedRef.current?.()
  }

  /** Drop (or move) the draggable pin on the map. */  function placeMarker(map, lat, lng) {
    if (markerRef.current) {
      markerRef.current.setLatLng([lat, lng])
    } else {
      const marker = L.marker([lat, lng], {
        icon: PIN_ICON,
        draggable: true,
        autoPan: true,
      }).addTo(map)
      marker.on('dragend', () => {
        const { lat: la, lng: ln } = marker.getLatLng()
        setPoint({ lat: round5(la), lon: round5(ln) })
        // STEP 26: MOVING THE PIN CLEARS A PREVIOUS REFUSAL. The message is about
        // the point the user has just abandoned, so leaving it up over the new
        // one would describe a location that is no longer selected.
        // STEP 27: it also clears the "found by search" label, for the same
        // reason - the pin is somewhere the search did not put it.
        setSearchPicked(null)
        onMovedRef.current?.()
      })
      markerRef.current = marker
    }
  }

  // Create the map when the modal opens; destroy it when it closes, so the
  // tile layer is not left running behind the page.
  useEffect(() => {
    if (!open || mapRef.current) return undefined
    const map = L.map(containerRef.current, {
      zoomControl: true,
      attributionControl: true,
      worldCopyJump: true,
    })
    mapRef.current = map
    const tiles = mapTileLayer()
    L.tileLayer(tiles.url, tiles.options).addTo(map)
    // STEP 26: THE PIN IS PLACED FROM THE CONTAINER'S OWN CLICK.
    //
    // Leaflet turns a map click into an event by hit-testing a tree of
    // absolutely-positioned panes stacked over the container, and it only fires
    // when that resolves to one of them. Measured inside the scrollable dialog,
    // a real click on the map reached the container and Leaflet never emitted
    // anything: the pin silently did not appear, leaving the user a map they
    // could look at but not use.
    //
    // Binding to the container and converting the click's own client
    // coordinates needs no pane at all - it is the container's own box, which is
    // precisely the element that was clicked - so pin placement no longer depends
    // on Leaflet's internal wiring. `invalidateSize()` keeps that box in step
    // with what is on screen, so the conversion stays correct at any size.
    function handleContainerClick(event) {
      const box = containerRef.current.getBoundingClientRect()
      const { lat, lng } = map.containerPointToLatLng(
        L.point(event.clientX - box.left, event.clientY - box.top),
      )
      setPoint({ lat: round5(lat), lon: round5(lng) })
      placeMarker(map, lat, lng)
      // A point the user has now placed or dragged is no longer "the place they
      // searched for", so the panel must stop describing it as such.
      setSearchPicked(null)
      onMovedRef.current?.()
    }
    // The same gesture by keyboard is handled by the container's own onKeyDown,
    // which is declared with the JSX so it can read this state.
    // Capture the node now: the ref may have changed by the time the cleanup
    // runs, and the listener must come off the same element it went on.
    const node = containerRef.current
    node.addEventListener('click', handleContainerClick)
    return () => {
      node.removeEventListener('click', handleContainerClick)
      map.remove()
      mapRef.current = null
      markerRef.current = null
    }
  }, [open])

  // On every open, size the map and centre it WITHOUT hardcoding a place:
  // a previous selection wins; otherwise the device's own location; failing
  // that a plain world view the user pans from before pinning.
  useEffect(() => {
    if (!open) return undefined
    const map = mapRef.current
    if (!map) return undefined
    // The container only gains its layout after the modal has rendered.
    setTimeout(() => map.invalidateSize(), 50)
    if (markerRef.current) {
      map.removeLayer(markerRef.current)
      markerRef.current = null
    }
    if (initial?.lat != null && initial?.lon != null) {
      map.setView([initial.lat, initial.lon], 14)
      setPoint({ lat: round5(initial.lat), lon: round5(initial.lon) })
      placeMarker(map, initial.lat, initial.lon)
      return undefined
    }
    setResolved(null)
    map.setView([0, 0], 2)
    setPoint(null)
    if ('geolocation' in navigator) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          if (!mapRef.current) return
          const { latitude, longitude } = position.coords
          mapRef.current.setView([latitude, longitude], 13)
          setPoint({ lat: round5(latitude), lon: round5(longitude) })
          placeMarker(mapRef.current, latitude, longitude)
        },
        () => {}, // stay on the world view; the user pans and taps instead
        { enableHighAccuracy: false, timeout: 8000, maximumAge: 600000 },
      )
    }
    return undefined
  }, [open, initial?.lat, initial?.lon])

  // STEP 25: NAME THE PIN WHILE IT IS STILL ON THE MAP.
  //
  // The point is reverse-geocoded on the SERVER, through the same endpoint every
  // other path uses, so the name beside the map is the geocoder's own answer and
  // cannot drift from the one that will appear on the card after confirming.
  //
  // TWO THINGS ARE GUARDED HERE, and both are about not showing a lie:
  //
  //   * A SUPERSEDED REQUEST NEVER COMMITS. Dragging the pin fires a lookup per
  //     change, and they can finish out of order; without the id guard a slow
  //     early request lands last and labels the pin with the wrong place.
  //   * A POINT THE GEOCODER CANNOT NAME SAYS SO. A fix in the sea or on a road
  //     the map does not describe comes back 404, and the modal reports that
  //     rather than keeping the previous pin's name - which would be a real
  //     place's name attached to a different point.
  useEffect(() => {
    if (!open || !point || typeof reverse !== 'function') {
      setResolved(null)
      setResolving(false)
      return undefined
    }
    let active = true
    setResolving(true)
    setResolved(null)
    reverse({ lat: point.lat, lon: point.lon })
      .then((place) => {
        if (!active) return
        setResolved(place ?? null)
      })
      .catch(() => {
        if (!active) return
        // Unresolvable is an honest state, not a reason to invent a name.
        setResolved(null)
      })
      .finally(() => {
        if (active) setResolving(false)
      })
    return () => {
      active = false
    }
    // The point is read through `point?.lat/lon` above: those are the deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, point?.lat, point?.lon, reverse])

  // STEP 27: THE IN-MAP AUTOCOMPLETE.
  //
  // One debounced request through the SAME `locationApi.search` the page's own
  // search box uses, so this is the same provider with the same ranking rather
  // than a second, divergent one.
  //
  // The request-id guard is what makes fast typing safe: a slow earlier lookup
  // must not land after a newer one and replace it with suggestions for text
  // the user has already changed.
  useEffect(() => {
    const text = searchText.trim()
    ++searchRequestId.current
    const id = searchRequestId.current
    // Text that came from a pick is not a query. Cancel any request still in
    // flight for it and leave the list closed.
    if (pickedRef.current) {
      clearTimeout(pendingSearch.current)
      setSuggestions([])
      setSearching(false)
      setSuggestionsOpen(false)
      return undefined
    }
    if (!open || text.length < 1) {
      setSuggestions([])
      setSearching(false)
      setSuggestionsOpen(false)
      setSearchError(null)
      return undefined
    }
    setSearching(true)
    setSuggestionsOpen(true)
    const timer = setTimeout(async () => {
      pendingSearch.current = null
      try {
        // `autocomplete: true` asks the backend for fewer spelling variants so
        // the first suggestion arrives quickly. It changes how much is searched,
        // never what: every row is still a real geocoder result.
        //
        // STEP 30: `state` / `district` are the device's OWN administrative area,
        // sent when known so the backend can rank a local place above a distant
        // one that matches the text just as well. They only REORDER - the
        // backend is given no ability to remove a place - so a user in one state
        // searching for a place in another still gets it.
        //
        // They are read from a ref rather than from props so this effect does not
        // have to re-run (and re-query) every time the device area resolves
        // mid-typing.
        const area = deviceAreaRef.current
        const response = await locationApi.search({
          q: text,
          limit: 8,
          autocomplete: true,
          ...(area?.state ? { state: area.state } : null),
          ...(area?.district ? { district: area.district } : null),
        })
        if (id !== searchRequestId.current) return
        setSuggestions(Array.isArray(response.data) ? response.data : [])
        setSearchError(null)
      } catch {
        if (id !== searchRequestId.current) return
        // A failed lookup shows NOTHING rather than a stale list, which would be
        // presented as if it matched what is now in the box.
        setSuggestions([])
        setSearchError(
          'Could not reach the search service. Check your connection, or place the pin on the map instead.',
        )
      } finally {
        if (id === searchRequestId.current) setSearching(false)
      }
    }, 300)
    pendingSearch.current = timer
    return () => {
      pendingSearch.current = null
      clearTimeout(timer)
    }
  }, [searchText, open])

  // STEP 27: A FRESH OPEN STARTS WITH AN EMPTY SEARCH BOX.
  //
  // Without this, closing the modal after a search and reopening it showed the
  // previous search's text in the box with a pin in a different part of the
  // world - which reads as "this is the place you are looking at" and is not.
  useEffect(() => {
    if (open) return
    // A reopened modal is a fresh question, not a continuation of the last one.
    pickedRef.current = false
    setSearchText('')
    setSuggestions([])
    setSuggestionsOpen(false)
    setSearchError(null)
    setSearchPicked(null)
  }, [open])

  /**
   * STEP 27: THE USER PICKED A PLACE FROM THE SEARCH.
   *
   * THE MAP MOVES TO IT AND THE PIN IS DROPPED THERE - the same pin, on the same
   * map, through the same `placeMarker` a tap uses. The modal is not replaced
   * and a second map is not created: this is the map the user was already
   * looking at, re-centred.
   *
   * THE PIN IS SET, NOT THE VIEW ALONE. A map that merely scrolled to a place
   * while the pin stayed behind would show the user two different things and let
   * them confirm the wrong one, and "Use This Location" acts on the PIN's
   * coordinates - so a view-only move would quietly select somewhere else.
   *
   * THE ZOOM IS CHOSEN BY WHAT IS BEING SHOWN. A single building needs a close
   * frame; a city or a district needs a wider one for its extent to be visible
   * at all. A fixed zoom framed a district so tightly the user saw one street.
   */
  function chooseSuggestion(candidate) {
    const map = mapRef.current
    setActiveIndex(-1)
    setEnterNotice(null)
    const lat = Number(candidate.lat)
    const lon = Number(candidate.lon)
    if (!map || !Number.isFinite(lat) || !Number.isFinite(lon)) return

    const isPoint = Boolean(candidate.poi_type) || candidate.kind === 'landmark'
    map.setView([lat, lon], isPoint ? 16 : 12)
    setPoint({ lat: round5(lat), lon: round5(lon) })
    placeMarker(map, lat, lon)
    setSearchPicked(candidate)
    // Set BEFORE the text, because the effect below runs on the text and must see
    // the flag already in place.
    pickedRef.current = true
    setSearchText(candidate.branch_label || candidate.label || candidate.name || '')
    setSuggestions([])
    setSuggestionsOpen(false)
    setSearchError(null)
    onMoved?.()
  }

  /**
   * STEP 31: WHAT THE KEYBOARD DOES INSIDE THE SEARCH BOX.
   *
   * ENTER IS A QUESTION WITH THREE POSSIBLE ANSWERS, and which one applies
   * depends on what is actually on screen:
   *
   *   * A row the user has highlighted  -> that row, and only that row, is used.
   *   * Exactly ONE suggestion          -> it is unambiguous, so it is used.
   *   * Several suggestions            -> NONE of them is silently chosen. The
   *     list is opened, the first row is highlighted, and the user is told to
   *     choose with the arrow keys or the mouse. Picking one of several matches
   *     for the user is exactly the ambiguity the brief forbids.
   *   * No suggestion yet / a lookup in
   *     flight                          -> nothing is chosen and the reason is
   *     stated, because a map that jumps while the answer is still arriving is
   *     a jump to a place nobody has seen.
   *
   * `preventDefault()` runs first on every handled key, including Enter. The
   * field sits inside the dialog, which can be rendered beneath the page's own
   * search <form>; without this a browser submit could resolve the PAGE's query
   * and, on the manual-prediction form, create a prediction from a search that
   * was only meant to move a map.
   */
  function handleSearchKeyDown(event) {
    const key = event.key
    if (key === 'ArrowDown' || key === 'ArrowUp') {
      if (suggestions.length === 0) return
      event.preventDefault()
      event.stopPropagation()
      setEnterNotice(null)
      setSuggestionsOpen(true)
      setActiveIndex((current) => {
        const step = key === 'ArrowDown' ? 1 : -1
        const next = current + step
        if (next < 0) return suggestions.length - 1
        if (next >= suggestions.length) return 0
        return next
      })
      return
    }
    if (key === 'Escape') {
      if (!suggestionsOpen) return
      // First Escape closes the LIST, not the whole dialog - the same two-step
      // behaviour every combobox has, and the reason the window-level handler
      // below does not fire here.
      event.preventDefault()
      event.stopPropagation()
      setSuggestionsOpen(false)
      setActiveIndex(-1)
      return
    }
    if (key !== 'Enter') return

    event.preventDefault()
    event.stopPropagation()

    if (activeIndex >= 0 && suggestions[activeIndex]) {
      chooseSuggestion(suggestions[activeIndex])
      return
    }
    if (searching) {
      setSuggestionsOpen(true)
      setEnterNotice('Still looking up that place — pick a suggestion once the list appears.')
      return
    }
    if (searchError) {
      setSuggestionsOpen(true)
      setEnterNotice('The lookup failed, so no place was selected. Try again, or place the pin on the map.')
      return
    }
    if (suggestions.length === 1) {
      chooseSuggestion(suggestions[0])
      return
    }
    if (suggestions.length > 1) {
      setSuggestionsOpen(true)
      setActiveIndex(0)
      setEnterNotice(
        `${suggestions.length} places match. Use the arrow keys or click one — nothing has been selected yet.`,
      )
      return
    }
    setSuggestionsOpen(true)
    setEnterNotice(
      'No matching place found, so the map was not moved. You can still drop a pin anywhere on the map.',
    )
  }

  // Escape closes the modal, like every other overlay in the application.
  useEffect(() => {
    if (!open) return undefined
    function onKey(event) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-label="Select your location on the map"
      onClick={onClose}
    >
      {/* The panel is scrollable rather than allowed to grow past the viewport.
          Without this, a short window clips the map itself: the dialog's content
          grows downwards, the map falls below the fold, and the user is left
          looking at a title and a button with no map between them. `max-h` with
          `overflow-y-auto` keeps the whole interaction reachable at any window
          size, which is what makes placing a pin possible at all. */}
      <div
        className="relative z-10 max-h-[92vh] w-full max-w-2xl overflow-y-auto overflow-x-hidden rounded-card bg-white shadow-panel dark:bg-slate-900"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-4 border-b border-slate-100 p-5 dark:border-slate-700">
          <div className="min-w-0">
            <h2 className="text-base font-semibold tracking-tight text-slate-900 dark:text-white">
              {mode === 'device' ? 'Your Current Location' : 'Select Your Location'}
            </h2>
            <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
              {mode === 'device'
                ? 'This is the position your device reported. The map is centred on it, and the place below is what it resolves to.'
                : 'Pan and zoom the map, tap to drop a pin, drag it to fine-tune.'}
            </p>
          </div>
          <Button variant="secondary" onClick={onClose} className="shrink-0 px-2.5 py-1.5 text-xs">
            Close
          </Button>
        </header>

        <div className="p-5">
          {/* --- STEP 27: SEARCH, AT THE TOP OF THE MAP POPUP ------------------
              The brief puts the search bar above the map, and that is where it
              goes - which is also the only order that works: searching before
              seeing the map means the map can be re-centred on the answer, and a
              map below the fold is not a map the user can check.

              The SAME provider as Location Prediction's own search
              (`locationApi.search`), so a place found here is the same place with
              the same name, the same branch and the same coordinates that the
              page-level box would have found. It is not a second geocoder. */}
          <div className="relative z-20 mb-4">
            {/* ONE STRAIGHT ROW: [ field (with its icon) ][ Enter button].
                The field is the only flexible child (`flex-1`) and the button is
                `shrink-0`, so the button sits at the search bar's RIGHT edge and
                the row never wraps to a second line at any width. `items-stretch`
                makes the button exactly as tall as the field, so the two line up
                on the same baseline rather than the button floating. */}
            <div className="flex items-stretch gap-2">
              <div className="relative min-w-0 flex-1">
            <span
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
              aria-hidden="true"
            >
              <Icon path={ICONS.search} className="h-4 w-4" />
            </span>
            <input
              ref={inputRef}
              type="text"
              value={searchText}
              onChange={(event) => {
                // Typing is a new question, so the pick marker is dropped and the
                // next keystroke searches again.
                pickedRef.current = false
                setActiveIndex(-1)
                setEnterNotice(null)
                setSearchText(event.target.value)
              }}
              onKeyDown={handleSearchKeyDown}
              onFocus={() => {
                if (suggestions.length > 0) setSuggestionsOpen(true)
              }}
              // The first Escape closes the LIST; only a later one, with nothing
              // open, is allowed to reach the window handler and close the dialog.
              onBlur={() => {
                optionRefs.current = []
              }}
              className="input pl-9"
              placeholder="Search a place to move the map here…"
              aria-label="Search for a location on the map"
              autoComplete="off"
              role="combobox"
              aria-expanded={suggestionsOpen}
              aria-controls="map-suggestions"
              aria-autocomplete="list"
              aria-activedescendant={
                activeIndex >= 0 && suggestions[activeIndex]
                  ? `map-suggestion-${activeIndex}`
                  : undefined
              }
              aria-describedby={enterNotice ? 'map-search-notice' : undefined}
              data-testid="map-search"
            />

            {/* THE SUGGESTION LIST LIVES IN A PORTAL, NOT HERE.

                It used to be an absolutely-positioned child of this wrapper,
                which is a DESCENDANT of the scrollable dialog (`max-h` +
                `overflow-y-auto`) — so once the list opened below the fold's
                top edge the ancestor's `overflow` clipped it and half the
                results were simply not there to read, while Leaflet's own
                controls (z-index 1000) also painted over it. The shared
                LocationSuggestions panel renders to <body> instead: it cannot
                be clipped by the dialog, it sits in front of the map, it keeps
                the dynamic height and the branch labelling, and its default
                z-index (1200) clears Leaflet's control pane.

                `open` is gated on the field having text, so the panel appears
                only while typing - an empty or cleared field closes it. */}
            <LocationSuggestions
              inputRef={inputRef}
              open={
                suggestionsOpen &&
                searchText.trim().length > 0 &&
                Boolean(searching || suggestions.length > 0 || searchError)
              }
              loading={searching}
              error={searchError}
              suggestions={suggestions}
              activeIndex={activeIndex}
              onHighlight={setActiveIndex}
              onChoose={chooseSuggestion}
              onClose={() => setSuggestionsOpen(false)}
              listId="map-suggestions"
              optionIdPrefix="map-suggestion"
              testIdPrefix="map-suggestion"
              optionRefs={optionRefs}
              /* The dialog is z-50 and the panel is a portal to <body>, so the
                 default 1200 would actually WIN against the dialog — but the
                 dialog is not the only thing above it. Leaflet's control pane is
                 z-index 1000 and the panel must clear it too, and a browser's
                 native UI can sit higher still. A near-maximum value makes the
                 "never behind the map" requirement unconditional rather than
                 dependent on the current z-ladder. */
              zIndex={2147483000}
            />
              </div>

              {/* THE GO BUTTON, at the search bar's right corner. Same handler
                  the Enter key runs, so keyboard and button cannot drift. It is a
                  SIBLING of the field's wrapper (not nested inside it), which is
                  what puts it to the right of the bar instead of overlapping the
                  field's own right padding. */}
              <Button
                onClick={() => handleSearchKeyDown({ key: 'Enter', preventDefault() {} })}
                className="shrink-0"
                aria-label="Search and move the map"
                data-testid="map-search-go"
              >
                <Icon path={ICONS.search} className="h-4 w-4" />
                Enter
              </Button>
            </div>
          </div>

          {/* STEP 31: WHY ENTER DID NOT MOVE THE MAP.

              Rendered directly under the field rather than inside the list, so
              the reason survives a suggestion being picked and is not scrolled
              away with the rows. `role="status"` makes it announced without
              stealing focus from the field. */}
          {enterNotice && (
            <p
              id="map-search-notice"
              role="status"
              data-testid="map-search-notice"
              className="mt-2 text-xs text-caution-dark dark:text-caution-light"
            >
              {enterNotice}
            </p>
          )}

          {/* The real map: Google Maps tiles when the key is configured, OSM
              tiles otherwise. Pan by dragging, zoom with the +/− controls or
              the mouse wheel, pin by tap, fine-tune by dragging the pin. */}
          <div
            ref={containerRef}
            className="h-80 w-full rounded-field border border-slate-200 dark:border-slate-600"
            role="application"
            aria-label="Interactive location map"
            /* STEP 26: focusable and a key handler, so the pin can be placed
               without a pointer. Leaflet overlays are pointer-transparent, so the
               container is the element that actually receives a click - which also
               makes it the right place to own the keyboard equivalent. */
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                handleKeyAtCentre()
              }
            }}
          />

          {/* STEP 25: THE PLACE, NAMED, BESIDE THE MAP.

              This is the reverse-geocode of the pin, read from the server, so it
              is the same answer the card will show after confirming. It appears
              HERE rather than only afterwards so the user can see what their
              position actually resolved to before committing to it — which is
              the difference between "use my location" and "use my location and
              check".

              Every field is the geocoder's own value or nothing. A field the data
              does not carry reads "Not available" and is never filled in from a
              neighbouring one: a district is never taken from the state, and an
              area is never taken from the city. */}
          <div
            className="mt-3 rounded-field border border-slate-200 bg-slate-50 p-3 dark:border-slate-600 dark:bg-slate-800"
            data-testid="map-place"
            aria-live="polite"
          >
            {resolving ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Working out which place this is…
              </p>
            ) : resolved ? (
              <>
                <p className="text-sm font-semibold text-slate-900 dark:text-white">
                  {resolved.name}
                </p>
                <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-3">
                  {[
                    ['Area', resolved.area],
                    ['City / Town', resolved.city],
                    ['District', resolved.district],
                    ['State', resolved.state],
                    ['Country', resolved.country],
                    ['Pincode', resolved.pincode],
                  ].map(([label, value]) => (
                    <div key={label} className="min-w-0">
                      <dt className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
                        {label}
                      </dt>
                      <dd className="truncate text-xs font-medium text-slate-700 dark:text-slate-200">
                        {value || 'Not available'}
                      </dd>
                    </div>
                  ))}
                </dl>
              </>
            ) : point ? (
              /* A point the geocoder cannot name. Said plainly, and the confirm
                 button stays available: the coordinates are real even when the
                 map has no name for them, and the parent's own reverse lookup
                 gets the final say. */
              <p className="text-sm text-slate-500 dark:text-slate-400">
                This position could not be matched to a place. You can still use it,
                or move the pin somewhere the map knows.
              </p>
            ) : (
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Tap anywhere on the map to place a pin.
              </p>
            )}
          </div>

          {/* STEP 26: THE REASON A CONFIRMED PIN WAS REFUSED, IN PLACE.

              The modal closing on confirm used to mean a failed lookup left the
              user with no card AND no map - the pin they had just placed, and
              the zoom they had just set, gone. Keeping the failure here instead
              means the map is still open, the pin is still where it was, and the
              only thing to do is move it or try again. */}
          {error && (
            <div
              role="alert"
              data-testid="map-error"
              className="mt-3 flex items-start gap-3 rounded-field border border-caution-light bg-caution-light/40 px-3 py-3 text-sm text-slate-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200"
            >
              <span className="mt-0.5 shrink-0 text-caution-dark" aria-hidden="true">
                <Icon path={ICONS.info} className="h-4 w-4" />
              </span>
              <p>
                {error}{' '}
                <span className="text-slate-500 dark:text-slate-400">
                  Your map and pin are still here — move the pin or try another point.
                </span>
              </p>
            </div>
          )}

          {/* THE RAW POINT. Deliberately not shown for a device fix.
              "Use my location" hands the server the user's exact position, and
              the brief asks not to expose raw coordinates unnecessarily: a pin
              the user dragged is a value they chose and are looking at, while an
              auto-detected position is personal data they never typed, so only
              the place it resolved to is shown. */}
          {point && mode !== 'device' && (
            <p className="mt-3 text-center text-xs text-slate-500 dark:text-slate-400">
              <span className="rounded-full bg-white/85 px-3 py-1 font-medium text-slate-600 tabular dark:bg-slate-800/85 dark:text-slate-300">
                {point.lat.toFixed(5)}, {point.lon.toFixed(5)}
              </span>
            </p>
          )}

          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              disabled={!point}
              loading={busy}
              onClick={() => point && onConfirm({ lat: point.lat, lon: point.lon })}
            >
              <Icon path={ICONS.check} className="h-4 w-4" />
              Use This Location
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
