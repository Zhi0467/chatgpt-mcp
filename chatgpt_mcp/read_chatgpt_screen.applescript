on run
	tell application "System Events"
		if not (exists process "ChatGPT") then
			return "{\"status\": \"error\", \"message\": \"ChatGPT process not found\"}"
		end if

		tell process "ChatGPT"
			-- Avoid forcing ChatGPT frontmost on every poll.
			delay 0.1

			if not (exists window 1) then
				return "{\"status\": \"error\", \"message\": \"No ChatGPT window found\"}"
			end if

			set allElements to entire contents of window 1
			set allTexts to {}
			set buttonsList to {}

			repeat with elem in allElements
				try
					set elemClass to class of elem

					if elemClass is static text then
						try
							set textContent to value of elem
							if textContent is missing value then
								set textContent to description of elem
							end if

							if textContent is not missing value and length of textContent > 0 then
								set trimmedText to textContent
								if trimmedText is not equal to "" and trimmedText is not equal to " " then
									set end of allTexts to textContent
								end if
							end if
						end try
					end if

					if elemClass is button then
						set end of buttonsList to elem
					end if
				end try
			end repeat

			-- Lightweight completion hint: incomplete while typing cursor is present.
			set conversationComplete to true
			repeat with t in allTexts
				if (contents of t) contains "▍" then
					set conversationComplete to false
					exit repeat
				end if
			end repeat

			set jsonResult to "{\"status\": \"success\", "
			set textCount to count of allTexts
			set jsonResult to jsonResult & "\"textCount\": " & textCount & ", \"texts\": ["

			repeat with i from 1 to textCount
				set currentText to item i of allTexts
				set currentText to my escapeJSON(currentText)
				set jsonResult to jsonResult & "\"" & currentText & "\""
				if i < textCount then
					set jsonResult to jsonResult & ", "
				end if
			end repeat

			set jsonResult to jsonResult & "], "
			set jsonResult to jsonResult & "\"indicators\": {"
			set jsonResult to jsonResult & "\"conversationComplete\": " & conversationComplete
			set jsonResult to jsonResult & "}}"

			return jsonResult
		end tell
	end tell
end run

on escapeJSON(txt)
	set txt to my replaceText(txt, "\\", "\\\\")
	set txt to my replaceText(txt, "\"", "\\\"")
	set txt to my replaceText(txt, return, "\\n")
	set txt to my replaceText(txt, linefeed, "\\n")
	set txt to my replaceText(txt, tab, "\\t")
	return txt
end escapeJSON

on replaceText(someText, oldItem, newItem)
	set {tempTID, AppleScript's text item delimiters} to {AppleScript's text item delimiters, oldItem}
	try
		set {textItems, AppleScript's text item delimiters} to {text items of someText, newItem}
		set {someText, AppleScript's text item delimiters} to {textItems as text, tempTID}
	on error errorMessage number errorNumber
		set AppleScript's text item delimiters to tempTID
		error errorMessage number errorNumber
	end try
	return someText
end replaceText
