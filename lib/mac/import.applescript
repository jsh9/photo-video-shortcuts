-- @NAME@: imports the files the shell made, each into the albums its
-- original is in, with what Photos has for its original (date, location,
-- title, caption, keywords, favorite) and the keyword "@COPY_KEYWORD@" with
-- its own (see copyKeywords), and collects every imported file's original in
-- the album "@ORIGINALS_ALBUM@", for the user to review and delete (a script
-- cannot delete them). The log says which copies lack their original's HDR.
--
-- Input (text, or a file holding it: see planText): one line per result,
-- "path|original id|delete or keep|name", then,
-- optionally, "|" and the copy's own keywords, separated by commas (Compress
-- Photos: its format and quality, "jxl,q=83"). The id may be empty when the
-- exported file could not be matched to an item; the flag is photobatch's
-- and is not acted on here.
-- Returns "imported=N", "collected=M", a line saying how long Photos took for
-- each step, then one "! ..." line per problem.
--
-- Photos' scripting is slow in a large library (58,000 items, 689 albums,
-- macOS 26): a call costs about 17 ms, an import about 0.5 s per file when
-- the files come one at a time, and a "whose" filter over the library about
-- 1.6 s. So the files are imported in one call, the albums' contents are
-- read one folder at a time, and the originals are referenced by id.
on run {input, parameters}
	set imported to 0
	set collected to 0
	set problems to ""
	set pairs to {} -- {original id, imported item, its own keywords}
	set toCollect to {} -- original ids
	set orphans to {} -- {imported item, its own keywords, name}: original unknown
	set tImport to 0
	set tCheck to 0
	set tAlbums to 0
	set tCollect to 0
	-- The plan: the files, their originals' ids, the flags and the names,
	-- from every item of the input (one text, or one file, normally: see
	-- planText). A plan that can't be read is a "!" line, and nothing is
	-- imported.
	set theFiles to {}
	set origIds to {}
	set flags to {}
	set names to {}
	set ownKeywords to {}
	set plan to ""
	try
		repeat with i from 1 to count of input
			set plan to plan & (my planText(item i of input)) & linefeed
		end repeat
	on error e number errNum
		set problems to problems & "! could not read the result lines (" & errNum & ": " & e & ")" & linefeed
		set plan to ""
	end try
	set oldDelims to AppleScript's text item delimiters
	set AppleScript's text item delimiters to "|"
	repeat with ln in paragraphs of plan
		set ln to ln as text
		if ln is not "" then
			set parts to text items of ln
			if (count of parts) < 4 then
				set problems to problems & "! unexpected result line: " & ln & linefeed
			else
				set end of theFiles to POSIX file (item 1 of parts)
				set end of origIds to item 2 of parts
				set end of flags to item 3 of parts
				set end of names to item 4 of parts
				if (count of parts) > 4 then
					set end of ownKeywords to item 5 of parts
				else
					set end of ownKeywords to ""
				end if
			end if
		end if
	end repeat
	set AppleScript's text item delimiters to oldDelims
	-- Import: all the files in one call; each imported item is matched to its
	-- line by file name (an import keeps the name, and the names are unique).
	-- If that call fails, one file at a time, so that one bad file doesn't
	-- fail the rest.
	if (count of theFiles) > 0 then
		set t0 to current date
		set newItems to {}
		try
			with timeout of 3600 seconds
				tell application "Photos" to set newItems to import theFiles skip check duplicates yes
			end timeout
		on error e number errNum
			-- A note, not a "!" problem: the files that then fail get their own.
			set problems to problems & "Photos did not take all the files in one import (" & errNum & ": " & e & "); they were imported one at a time." & linefeed
			set newItems to {}
			repeat with i from 1 to count of theFiles
				try
					with timeout of 3600 seconds
						tell application "Photos" to set newItems to newItems & (import {item i of theFiles} skip check duplicates yes)
					end timeout
				on error e number errNum
					set problems to problems & "! " & (item i of names) & ": import failed (" & errNum & ": " & e & ")" & linefeed
				end try
			end repeat
		end try
		set newNames to {}
		tell application "Photos"
			repeat with newItem in newItems
				set end of newNames to filename of newItem
			end repeat
		end tell
		repeat with i from 1 to count of names
			set jxlName to item i of names
			set found to missing value
			repeat with j from 1 to count of newNames
				if (item j of newNames) is jxlName then
					set found to item j of newItems
					exit repeat
				end if
			end repeat
			if found is missing value then
				set problems to problems & "! " & jxlName & ": Photos did not import it" & linefeed
			else
				set imported to imported + 1
				set origId to item i of origIds
				if origId is not "" then
					set end of pairs to {origId, found, item i of ownKeywords}
					set end of toCollect to origId
				else
					set end of orphans to {found, item i of ownKeywords, jxlName}
					set problems to problems & "! " & jxlName & ": saved, but its original is unknown, so it was not added to albums" & linefeed
				end if
			end if
		end repeat
		set tImport to (current date) - t0
	end if
	-- What Photos has for each original: photobatch wrote its date and
	-- location into the copy's file, for Photos to read on import; should
	-- Photos have read something else, the copy gets the original's. Its
	-- title, caption, keywords and favorite stay in Photos' library, never in
	-- the copy's file (the file keeps only what the original's file has), so
	-- they are set here, the keywords with "@COPY_KEYWORD@" and the copy's own
	-- added (copyKeywords). One call reads all of an item ("properties
	-- of", its fields named by their codes: see export.applescript), and one
	-- sets each field that differs. A field Photos won't set is a "!" line,
	-- and the next field is still tried. The log counts the fields set, the
	-- keywords excepted: every copy gets its keywords here.
	set t0 to current date
	if (count of pairs) > 0 then
		set redated to 0
		set relocated to 0
		set retitled to 0
		set recaptioned to 0
		set favorited to 0
		tell application "Photos"
			repeat with pair in pairs
				set want to missing value
				set got to missing value
				try
					set want to properties of media item id ((item 1 of pair) as text)
					set got to properties of (item 2 of pair)
				on error e number errNum
					set problems to problems & "! " & (item 1 of pair) & ": could not read the copy or its original in Photos (" & errNum & ": " & e & ")" & linefeed
				end try
				if want is not missing value and got is not missing value then
					set copyItem to item 2 of pair
					try
						if («class idat» of got) is not («class idat» of want) then
							set date of copyItem to «class idat» of want
							set redated to redated + 1
						end if
					on error e number errNum
						set problems to problems & (my notSet(got, "date", errNum, e))
					end try
					try
						if not my sameLocation(«class IPlo» of got, «class IPlo» of want) then
							-- {missing value, missing value} removes it
							set location of copyItem to «class IPlo» of want
							set relocated to relocated + 1
						end if
					on error e number errNum
						set problems to problems & (my notSet(got, "location", errNum, e))
					end try
					try
						if not my sameText(«class pnam» of got, «class pnam» of want) then
							set name of copyItem to my textOf(«class pnam» of want)
							set retitled to retitled + 1
						end if
					on error e number errNum
						set problems to problems & (my notSet(got, "title", errNum, e))
					end try
					try
						if not my sameText(«class IPde» of got, «class IPde» of want) then
							set description of copyItem to my textOf(«class IPde» of want)
							set recaptioned to recaptioned + 1
						end if
					on error e number errNum
						set problems to problems & (my notSet(got, "caption", errNum, e))
					end try
					try
						set wantKeywords to my copyKeywords(«class IPkw» of want, item 3 of pair)
						if not my sameKeywords(«class IPkw» of got, wantKeywords) then
							set keywords of copyItem to wantKeywords
						end if
					on error e number errNum
						set problems to problems & (my notSet(got, "keywords", errNum, e))
					end try
					try
						if («class IPfv» of want) and not («class IPfv» of got) then
							set favorite of copyItem to true
							set favorited to favorited + 1
						end if
					on error e number errNum
						set problems to problems & (my notSet(got, "favorite", errNum, e))
					end try
				end if
			end repeat
		end tell
		if redated > 0 then set problems to problems & "Photos dated " & redated & " copy(ies) differently from the original; they now have the original's date." & linefeed
		if relocated > 0 then set problems to problems & relocated & " copy(ies) got their original's location in Photos (Photos showed another)." & linefeed
		if retitled > 0 then set problems to problems & retitled & " copy(ies) got their original's title in Photos." & linefeed
		if recaptioned > 0 then set problems to problems & recaptioned & " copy(ies) got their original's caption in Photos." & linefeed
		if favorited > 0 then set problems to problems & favorited & " copy(ies) marked as favorites, as their originals are." & linefeed
	end if
	-- A copy whose original is unknown still gets "@COPY_KEYWORD@" and its own
	-- keywords, with those Photos read from its file.
	repeat with o in orphans
		try
			tell application "Photos"
				set had to keywords of (item 1 of o)
				set keywords of (item 1 of o) to my copyKeywords(had, item 2 of o)
			end tell
		on error e number errNum
			set problems to problems & "! " & (item 3 of o) & ": could not set its keywords (" & errNum & ": " & e & ")" & linefeed
		end try
	end repeat
	set tCheck to (current date) - t0
	-- Albums: each new item joins every album its original is in. The albums'
	-- contents are read one folder at a time (addToAlbums), one call for all of
	-- a folder's albums, where a call per album would take 12 s for 689
	-- albums, and used as they come, so that no list of every album's ids is
	-- built up (AppleScript copies lists on every assignment).
	if (count of pairs) > 0 then
		set t0 to current date
		with timeout of 3600 seconds
			tell application "Photos"
				set problems to problems & (my addToAlbums(albums, (id of media items of albums), folders, pairs))
			end tell
		end timeout
		set tAlbums to (current date) - t0
	end if
	-- The converted originals, in one album.
	if (count of toCollect) > 0 then
		set t0 to current date
		try
			tell application "Photos"
				set foundAlbums to (albums whose name is "@ORIGINALS_ALBUM@")
				if (count of foundAlbums) > 0 then
					set target to item 1 of foundAlbums
				else
					set target to make new album named "@ORIGINALS_ALBUM@"
				end if
				-- By reference (media item id X), not a "whose id is" filter: the
				-- filter scans the whole library, about 1.6 s per item in a
				-- library of 58,000 items; the reference is immediate.
				set originals to {}
				repeat with oid in toCollect
					try
						set end of originals to media item id (oid as text)
					end try
				end repeat
				if (count of originals) > 0 then
					add originals to target
					set collected to count of originals
				end if
			end tell
		on error e number errNum
			set problems to problems & "! could not collect the originals in the album @ORIGINALS_ALBUM@ (" & errNum & ": " & e & ")" & linefeed
		end try
		set tCollect to (current date) - t0
	end if
	return "imported=" & imported & linefeed & "collected=" & collected & linefeed & "Photos took " & tImport & " s to import, " & tCheck & " s to check the copies against their originals, " & tAlbums & " s for the albums and " & tCollect & " s to collect the originals." & linefeed & problems
end run

-- Adds each new item of pairs ({original id, item, its own keywords}) to the albums of
-- albumList its original is in, then, recursively, to those in the folders of
-- folderList. albumIds is "id of media items of" the same albums, one list
-- per album, which the caller fetches in one call. Returns the "! ..." lines.
on addToAlbums(albumList, albumIds, folderList, pairs)
	set problems to ""
	repeat with i from 1 to count of albumList
		set members to {}
		repeat with pair in pairs
			if (item i of albumIds) contains (item 1 of pair) then set end of members to item 2 of pair
		end repeat
		-- The review albums "@ORIGINALS_ALBUM@" and "@OLD_ORIGINALS_ALBUM@"
		-- (an earlier version's) hold originals already converted once; a
		-- copy must not join them, or it could be deleted with them.
		if (count of members) > 0 and (name of (item i of albumList)) is not in {"@ORIGINALS_ALBUM@", "@OLD_ORIGINALS_ALBUM@"} then
			tell application "Photos"
				try
					add members to (item i of albumList)
				on error e number errNum
					set problems to problems & "! album " & (name of (item i of albumList)) & ": " & e & linefeed
				end try
			end tell
		end if
	end repeat
	repeat with f in folderList
		tell application "Photos"
			set problems to problems & (my addToAlbums(albums of f, (id of media items of (albums of f)), folders of f, pairs))
		end tell
	end repeat
	return problems
end addToAlbums

-- The "!" line for a field of a copy (its properties record `got`) Photos
-- wouldn't set.
on notSet(got, field, errNum, e)
	return "! " & («class filn» of got) & ": could not set its " & field & " (" & errNum & ": " & e & ")" & linefeed
end notSet

-- The plan's text from one item of the run's input. Shortcuts types the
-- shell script's output by its content, and when it takes it for something
-- other than text it passes a file ("stdout") instead: three or more lines
-- with a comma each are CSV to it (Compress Photos' keywords, "jxl,q=83", or
-- names with commas; macOS 26). Its text is then read from the file; an
-- empty file is no lines, and any other failure to read it is the caller's
-- to report.
on planText(v)
	if class of v is in {alias, «class furl», file} then
		try
			return read v as «class utf8»
		on error number -39 -- an empty file: end of file
			return ""
		end try
	end if
	return v as text
end planText

-- Locations as Photos gives them ({latitude, longitude}, or two missing
-- values): the same place within 0.00001 degree (about 1 m), as photobatch
-- compares them.
on sameLocation(a, b)
	set aNone to (item 1 of a) is missing value or (item 2 of a) is missing value
	set bNone to (item 1 of b) is missing value or (item 2 of b) is missing value
	if aNone or bNone then return aNone and bNone
	return my near(item 1 of a, item 1 of b) and my near(item 2 of a, item 2 of b)
end sameLocation

on near(x, y)
	set d to x - y
	if d < 0 then set d to -d
	return d is less than or equal to 1.0E-5
end near

-- A title or caption: missing value and "" are both none.
on textOf(v)
	if v is missing value then return ""
	return v as text
end textOf

on sameText(a, b)
	considering case
		return (my textOf(a)) is (my textOf(b))
	end considering
end sameText

-- Keywords: missing value is none; the same in any order.
on listOf(v)
	if v is missing value then return {}
	return v
end listOf

-- The keywords a copy gets in Photos: its original's (`v`, as Photos gives
-- them); then "@COPY_KEYWORD@", which every copy gets; then its own (`own`,
-- from its result line, separated by commas: Compress Photos gives its format
-- and quality, "jxl,q=83" or "heic,rf=26"). An original that is itself a copy
-- (it has "@COPY_KEYWORD@") passes on none of the keywords the tool gave it
-- (toolKeyword), so a copy of a copy (a HEIC copy converted again, to JPEG
-- XL) has only its own format and quality, and one "@COPY_KEYWORD@". Any
-- other original's keywords are all kept, a "heic" or "q=..." of the user's
-- own too.
on copyKeywords(v, own)
	set originalKeywords to my listOf(v)
	set isCopy to false
	repeat with k in originalKeywords
		if (contents of k) is "@COPY_KEYWORD@" then set isCopy to true
	end repeat
	set kws to {}
	repeat with k in originalKeywords
		set kw to contents of k
		if not (isCopy and my toolKeyword(kw)) then set end of kws to kw
	end repeat
	set end of kws to "@COPY_KEYWORD@"
	set oldDelims to AppleScript's text item delimiters
	set AppleScript's text item delimiters to ","
	set ownList to text items of (own as text)
	set AppleScript's text item delimiters to oldDelims
	repeat with k in ownList
		set kw to contents of k
		if kw is not "" then set end of kws to kw
	end repeat
	return kws
end copyKeywords

-- Whether `kw` is a keyword the tool gives its copies: "@COPY_KEYWORD@", a
-- format keyword (Compress Photos: "heic", "jxl") or a quality keyword
-- ("q=83", "rf=26"). AppleScript compares text ignoring case.
on toolKeyword(kw)
	if kw is "@COPY_KEYWORD@" then return true
	repeat with f in @FORMAT_KEYWORDS@
		if kw is (contents of f) then return true
	end repeat
	repeat with pfx in @QUALITY_PREFIXES@
		if kw begins with (contents of pfx) then return true
	end repeat
	return false
end toolKeyword

on sameKeywords(a, b)
	set a to my listOf(a)
	set b to my listOf(b)
	considering case
		repeat with k in a
			if (contents of k) is not in b then return false
		end repeat
		repeat with k in b
			if (contents of k) is not in a then return false
		end repeat
	end considering
	return true
end sameKeywords
