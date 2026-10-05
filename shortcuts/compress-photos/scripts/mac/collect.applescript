-- Compress Photos (macOS), picker route: collects the originals whose JPEG XL
-- has everything they have in the album "@ORIGINALS_ALBUM@", for the user to
-- delete. (Shortcuts' Delete Photos needs a prompt the Shortcuts app often
-- can't show on macOS 26, and a script can't delete photos.)
--
-- Input: one line per original, its name as Shortcuts gives it ("IMG_0087.HEIC"
-- or "IMG_0087"). A name that matches no photo, or several, is skipped with a
-- note: nothing but the photo itself may be collected.
-- Returns "collected=N", then one "! ..." line per problem.
on run {input, parameters}
	set collected to 0
	set problems to ""
	set originals to {}
	if (count of input) > 0 then
		set namesText to item 1 of input as text
		repeat with ln in paragraphs of namesText
			set ln to ln as text
			if ln is not "" then
				try
					tell application "Photos" to set hits to (media items whose filename contains ln)
					set matches to {}
					repeat with i from 1 to count of hits
						set m to item i of hits
						tell application "Photos" to set fn to filename of m
						if fn is ln or fn starts with (ln & ".") then set end of matches to m
					end repeat
					if (count of matches) is 1 then
						set end of originals to item 1 of matches
					else if (count of matches) is 0 then
						set problems to problems & "! " & ln & ": not found in Photos, so not collected for deletion" & linefeed
					else
						set problems to problems & "! " & ln & ": " & (count of matches) & " photos have this name, so none was collected for deletion" & linefeed
					end if
				on error e number errNum
					set problems to problems & "! " & ln & ": " & e & linefeed
				end try
			end if
		end repeat
	end if
	if (count of originals) > 0 then
		try
			tell application "Photos"
				set found to (albums whose name is "@ORIGINALS_ALBUM@")
				if (count of found) > 0 then
					set target to item 1 of found
				else
					set target to make new album named "@ORIGINALS_ALBUM@"
				end if
				add originals to target
				set collected to count of originals
			end tell
		on error e number errNum
			set problems to problems & "! could not collect the originals in the album @ORIGINALS_ALBUM@ (" & errNum & ": " & e & ")" & linefeed
		end try
	end if
	return "collected=" & collected & linefeed & problems
end run
