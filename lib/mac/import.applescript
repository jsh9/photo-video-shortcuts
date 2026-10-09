-- @NAME@: imports the files the shell made, each into the albums its
-- original is in, with its original's date, and collects every imported
-- file's original in the album "@ORIGINALS_ALBUM@", for the user to review
-- and delete (a script cannot delete them). The log says which copies lack
-- their original's HDR.
--
-- Input: one line per result, "path|original id|delete or keep|name" (the id
-- may be empty when the exported file could not be matched to an item; the
-- flag is jxlbatch's and is not acted on here).
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
	set pairs to {} -- {original id, imported item}
	set toCollect to {} -- original ids
	set tImport to 0
	set tAlbums to 0
	set tCollect to 0
	-- The plan: the files, their originals' ids, the flags and the names.
	set theFiles to {}
	set origIds to {}
	set flags to {}
	set names to {}
	if (count of input) > 0 then
		set plan to item 1 of input as text
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
				end if
			end if
		end repeat
		set AppleScript's text item delimiters to oldDelims
	end if
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
					set end of pairs to {origId, found}
					set end of toCollect to origId
				else
					set problems to problems & "! " & jxlName & ": saved, but its original is unknown, so it was not added to albums" & linefeed
				end if
			end if
		end repeat
		set tImport to (current date) - t0
	end if
	-- Dates: each copy has its original's date in Photos, which jxlbatch
	-- wrote into the file (EXIF) for Photos to read on import. Should Photos
	-- have read another, the copy gets the original's (two calls per copy).
	if (count of pairs) > 0 then
		set redated to 0
		tell application "Photos"
			repeat with pair in pairs
				try
					set want to date of media item id ((item 1 of pair) as text)
					set copyItem to item 2 of pair
					if (date of copyItem) is not want then
						set date of copyItem to want
						set redated to redated + 1
					end if
				end try
			end repeat
		end tell
		if redated > 0 then set problems to problems & "Photos dated " & redated & " copy(ies) differently from the original; they now have the original's date." & linefeed
	end if
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
	return "imported=" & imported & linefeed & "collected=" & collected & linefeed & "Photos took " & tImport & " s to import, " & tAlbums & " s for the albums and " & tCollect & " s to collect the originals." & linefeed & problems
end run

-- Adds each new item of pairs ({original id, item}) to the albums of
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
		-- The review album "@ORIGINALS_ALBUM@" holds originals already
		-- converted once; a copy must not join it, or it could be deleted
		-- with them.
		if (count of members) > 0 and (name of (item i of albumList)) is not "@ORIGINALS_ALBUM@" then
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
