-- @NAME@: exports the original files of the items selected in Photos into
-- <work>/in (input: the work folder's path), and returns one line per
-- selected item, "id|date|filename", for the shell to match the exported
-- files to the items (a Live Photo is one item, exported as a photo and a
-- .mov). The date is the item's in Photos, "2024-01-01 17:00:00" as the Mac's
-- clock shows it (Photos gives it in the Mac's time zone; the shell adds the
-- offset), empty if Photos gives none.
-- Then, per item, its location in Photos, "id<tab>gps<tab>value" (no "|" in
-- it, so a reader of the first lines alone skips it): "40.758442,-73.829767"
-- and ",11.73" for the altitude when Photos has one other than 0; empty when
-- it has no location, as for a location hidden in Photos. Its title, caption
-- and keywords aren't given: they stay in Photos' library, never in the
-- copy's file (import.applescript sets them on the copy in Photos).
-- "using originals": the file as it was recorded or imported (an edited
-- item's edits are not applied, nor a date changed in Photos); without it,
-- Photos renders a copy. On an error, returns "ERROR: ...".
--
-- One Apple event per item reads all of it: "properties of" (about 18 ms in a
-- library of 58,000 items, against about 16 ms for one property). Inside
-- "tell application "Photos"" the record's fields are named by their codes
-- («class idat» is its date: "date of" the record is taken for AppleScript's
-- own date class there).
on run {input, parameters}
	try
		set work to item 1 of input as text
		set dest to POSIX file (work & "/in/")
		-- Exporting many items, or ones iCloud must first download, takes
		-- longer than AppleScript's default 2-minute limit on one command.
		with timeout of 3600 seconds
			tell application "Photos"
				set sel to selection
				if (count of sel) is 0 then return "ERROR: nothing is selected in Photos."
				set idText to ""
				set metaText to ""
				repeat with i from 1 to count of sel
					set p to properties of (item i of sel)
					set itemId to «class ID  » of p
					set dateText to ""
					try
						set dateText to my wallTime(«class idat» of p)
					end try
					set idText to idText & itemId & "|" & dateText & "|" & («class filn» of p) & linefeed
					-- An item whose record can't be read gets no lines (the
					-- file's values stay) rather than failing the export.
					try
						set metaText to metaText & my metaLines(itemId, p)
					end try
				end repeat
				export sel to dest with using originals
			end tell
		end timeout
		return idText & metaText
	on error e number errNum
		return "ERROR: Photos could not export the selected items (" & errNum & ": " & e & ")"
	end try
end run

-- "2024-01-01 17:00:00"
on wallTime(d)
	set t to time of d
	return (year of d as text) & "-" & my two(month of d as integer) & "-" & my two(day of d) & " " & my two(t div hours) & ":" & my two((t mod hours) div minutes) & ":" & my two(t mod minutes)
end wallTime

on two(n)
	return text -2 thru -1 of ("0" & n)
end two

-- The item's location in Photos (its properties record `p`), as an
-- "id<tab>gps<tab>value" line.
on metaLines(itemId, p)
	set gps to ""
	set loc to «class IPlo» of p
	if (count of loc) is 2 then
		if (item 1 of loc) is not missing value and (item 2 of loc) is not missing value then
			set gps to my decimalText(item 1 of loc, 6) & "," & my decimalText(item 2 of loc, 6)
			set alti to missing value
			try
				set alti to «class alti» of p
			end try
			-- 0: no altitude (a place typed in Photos' Info window gets 0.0); nor
			-- one of 100 km or more (a corrupt GPSAltitude; photobatch takes
			-- none either), which would overflow decimalText's whole number
			if alti is not missing value and alti is not 0 and alti > -100000 and alti < 100000 then
				set gps to gps & "," & my decimalText(alti, 2)
			end if
		end if
	end if
	return itemId & tab & "gps" & tab & gps & linefeed
end metaLines

-- `x` with `places` decimals ("-73.829767"), from a whole number: a real's
-- text follows the Mac's number format ("40,7" in some regions) and turns to
-- E notation. 10^places * x stays below 2^29 here, so it is an integer.
on decimalText(x, places)
	set factor to (10 ^ places) as integer
	set n to round (x * factor) rounding as taught in school
	set minus to ""
	if n < 0 then
		set minus to "-"
		set n to -n
	end if
	set digits to (n mod factor) as text
	repeat while (count of digits) < places
		set digits to "0" & digits
	end repeat
	return minus & ((n div factor) as text) & "." & digits
end decimalText
