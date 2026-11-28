-- @NAME@: the album "@BRIDGE_ALBUM@", through which Shortcuts' Find Photos
-- gets the videos to convert as library items (no Shortcuts action takes an
-- item's id), so that an edited video comes as Photos' own version of it (see
-- DEVELOPING.md, "Edited videos"). Compress Photos has its own copy, which
-- leaves videos out.
--
-- Input "close": deletes every top-level album with that name (no video is
-- deleted) and returns "CLOSED". Any other input is the planning pass's
-- result (text, or a file holding it: see planText), one "id|date|filename"
-- line per video it will convert: every album with that name is deleted, a
-- new one is made, and each line's item is added to it. Returns "BRIDGE n", n
-- the items the album then holds; "BRIDGE 0" and no album when there is
-- nothing to add (no input at all, too). On an error, returns "ERROR: ...". A
-- user's own top-level album with that name (compared without case) is
-- deleted too; no video is. No Shortcuts variable may appear in this text:
-- the script would not compile.
on run {input, parameters}
	set what to "fill"
	try
		set lines_ to ""
		repeat with i from 1 to count of input
			set lines_ to lines_ & (my planText(item i of input)) & linefeed
		end repeat
		set closing to (lines_ is not "") and ((paragraph 1 of lines_) is "close")
		if closing then set what to "delete"
		with timeout of 3600 seconds
			tell application "Photos"
				set olds to (albums whose name is "@BRIDGE_ALBUM@")
				repeat with a in olds
					delete (contents of a)
				end repeat
			end tell
			if closing then return "CLOSED"
			set ids to my itemIds(lines_)
			if (count of ids) is 0 then return "BRIDGE 0"
			tell application "Photos"
				-- By reference (media item id X), not a "whose id is" filter,
				-- which scans the whole library (see import.applescript).
				set items_ to {}
				repeat with oid in ids
					try
						set end of items_ to media item id (oid as text)
					end try
				end repeat
				if (count of items_) is 0 then return "BRIDGE 0"
				set bridge to make new album named "@BRIDGE_ALBUM@"
				add items_ to bridge
				return "BRIDGE " & (count of media items of bridge)
			end tell
		end timeout
	on error e number errNum
		return "ERROR: Photos could not " & what & " the album @BRIDGE_ALBUM@ (" & errNum & ": " & e & ")"
	end try
end run

-- The ids of the "id|date|filename" lines; an "ERROR: ..." line gives none.
on itemIds(t)
	set ids to {}
	set oldDelims to AppleScript's text item delimiters
	set AppleScript's text item delimiters to "|"
	repeat with ln in paragraphs of t
		set ln to ln as text
		if ln contains "|" and ln does not contain tab and not (ln starts with "ERROR") then
			set oid to text item 1 of ln
			if oid is not "" then set end of ids to oid
		end if
	end repeat
	set AppleScript's text item delimiters to oldDelims
	return ids
end itemIds

-- The text of one item of the run's input: Shortcuts may pass a file instead
-- of text (see import.applescript's planText).
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
