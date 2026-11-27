-- @NAME@: the album "@BRIDGE_ALBUM@", through which Shortcuts' Find Photos
-- gets the photos selected in Photos as library photos (no Shortcuts action
-- takes a photo's id), so that an edited photo comes as Photos' own rendering
-- of it (see DEVELOPING.md, "On the Mac").
--
-- Input "close": deletes every top-level album with that name (no photo is
-- deleted) and returns "CLOSED". Any other input is export.applescript's
-- result (text, or a file holding it: see planText): every album with that
-- name is deleted, a new one is made, and each item of an "id|date|filename"
-- line is added to it, except videos (".mov", ".mp4", ".m4v"; a Live Photo's
-- still can't be told from a photo here). Returns "BRIDGE n", n the items the
-- album then holds; "BRIDGE 0" and no album when there is nothing to add (only
-- videos, or the export failed). On an error, returns "ERROR: ...". No
-- Shortcuts variable may appear in this text: the script would not compile.
on run {input, parameters}
	try
		set lines_ to ""
		repeat with i from 1 to count of input
			set lines_ to lines_ & (my planText(item i of input)) & linefeed
		end repeat
		with timeout of 3600 seconds
			tell application "Photos"
				set olds to (albums whose name is "@BRIDGE_ALBUM@")
				repeat with a in olds
					delete (contents of a)
				end repeat
			end tell
			if (paragraph 1 of lines_) is "close" then return "CLOSED"
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
		return "ERROR: Photos could not fill the album @BRIDGE_ALBUM@ (" & errNum & ": " & e & ")"
	end try
end run

-- The ids of export.applescript's "id|date|filename" lines, videos left out.
-- Its "id<tab>field<tab>value" lines and an "ERROR: ..." line give none.
on itemIds(t)
	set ids to {}
	set oldDelims to AppleScript's text item delimiters
	set AppleScript's text item delimiters to "|"
	repeat with ln in paragraphs of t
		set ln to ln as text
		if ln contains "|" and ln does not contain tab and not (ln starts with "ERROR") then
			if not (ln ends with ".mov" or ln ends with ".mp4" or ln ends with ".m4v") then
				set oid to text item 1 of ln
				if oid is not "" then set end of ids to oid
			end if
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
