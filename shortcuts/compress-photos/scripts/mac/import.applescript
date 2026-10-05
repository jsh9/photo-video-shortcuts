-- Compress Photos (macOS): imports the JPEG XL files the shell made, each into
-- the albums its original is in, and collects the originals whose JPEG XL has
-- everything they have in the album "@ORIGINALS_ALBUM@", for the user to
-- delete (a script cannot delete photos).
--
-- Input: one line per result, "path|original id|delete or keep|name" (the id
-- may be empty when the exported file could not be matched to a photo).
-- Returns "imported=N", "collected=M", then one "! ..." line per problem.
on run {input, parameters}
	set imported to 0
	set collected to 0
	set problems to ""
	set pairs to {} -- {original id, imported item}
	set toCollect to {} -- original ids
	if (count of input) > 0 then
		set plan to item 1 of input as text
		set oldDelims to AppleScript's text item delimiters
		repeat with ln in paragraphs of plan
			set ln to ln as text
			if ln is not "" then
				set jxlName to ln
				try
					set AppleScript's text item delimiters to "|"
					set parts to text items of ln
					set AppleScript's text item delimiters to oldDelims
					if (count of parts) < 4 then error "unexpected result line"
					set f to POSIX file (item 1 of parts)
					set origId to item 2 of parts
					set flag to item 3 of parts
					set jxlName to item 4 of parts
					with timeout of 3600 seconds
						tell application "Photos" to set newItems to import {f} skip check duplicates yes
					end timeout
					if (count of newItems) > 0 then
						set imported to imported + 1
						if origId is not "" then
							set end of pairs to {origId, item 1 of newItems}
							if flag is "delete" then set end of toCollect to origId
						else
							set problems to problems & "! " & jxlName & ": saved, but its original is unknown, so it was not added to albums" & linefeed
						end if
					else
						set problems to problems & "! " & jxlName & ": Photos did not import it" & linefeed
					end if
				on error e number errNum
					set AppleScript's text item delimiters to oldDelims
					set problems to problems & "! " & jxlName & ": import failed (" & errNum & ": " & e & ")" & linefeed
				end try
			end if
		end repeat
	end if
	-- Albums: every album, nested ones included, with the ids of its items,
	-- read one level at a time (scanAlbums): one call per folder for all of
	-- its albums' ids, where a call per album costs about 17 ms, 12 s for a
	-- library of 689 albums. Each new item joins every album its original is
	-- in.
	if (count of pairs) > 0 then
		with timeout of 3600 seconds
		tell application "Photos"
			set scanned to my scanAlbums(albums, (id of media items of albums), folders)
			repeat with entry in scanned
				set a to item 1 of entry
				set ids to item 2 of entry
				set members to {}
				repeat with pair in pairs
					if ids contains (item 1 of pair) then set end of members to item 2 of pair
				end repeat
				if (count of members) > 0 then
					try
						add members to a
					on error e number errNum
						set problems to problems & "! album " & (name of a) & ": " & e & linefeed
					end try
				end if
			end repeat
		end tell
		end timeout
	end if
	-- The originals to delete, in one album.
	if (count of toCollect) > 0 then
		try
			tell application "Photos"
				set found to (albums whose name is "@ORIGINALS_ALBUM@")
				if (count of found) > 0 then
					set target to item 1 of found
				else
					set target to make new album named "@ORIGINALS_ALBUM@"
				end if
				-- By reference (media item id X), not a "whose id is" filter: the
				-- filter scans the whole library, about 1.6 s per photo in a
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
	end if
	return "imported=" & imported & linefeed & "collected=" & collected & linefeed & problems
end run

-- {album, ids of its items} for each album of albumList and, recursively, of
-- the folders in folderList. albumIds is "id of media items of" the same
-- albums, which the caller fetches in one call (one list per album).
on scanAlbums(albumList, albumIds, folderList)
	set found to {}
	repeat with i from 1 to count of albumList
		set end of found to {item i of albumList, item i of albumIds}
	end repeat
	repeat with f in folderList
		tell application "Photos"
			set found to found & (my scanAlbums(albums of f, (id of media items of (albums of f)), folders of f))
		end tell
	end repeat
	return found
end scanAlbums
