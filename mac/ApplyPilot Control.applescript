-- ApplyPilot Control: start, stop, and restart ApplyPilot without a terminal.
-- `./applypilot install` compiles this into ~/Applications/ApplyPilot Control.app.
property cli : "__APPLYPILOT__"

on run
	set statusLine to my sh("status --short")
	set actions to {"Open ApplyPilot", "Restart", "Stop", "Start", "Switch to development mode", "Switch to production mode", "Show logs"}
	set picked to choose from list actions with title "ApplyPilot Control" with prompt "ApplyPilot: " & statusLine default items {"Open ApplyPilot"} OK button name "Run" cancel button name "Close"
	if picked is false then return
	set action to item 1 of picked
	try
		if action is "Open ApplyPilot" then
			my sh("open")
		else if action is "Restart" then
			display notification "Restarting…" with title "ApplyPilot"
			my finish(my sh("restart"))
		else if action is "Stop" then
			my finish(my sh("stop"))
		else if action is "Start" or action is "Switch to production mode" then
			display notification "Starting in production mode…" with title "ApplyPilot"
			my finish(my sh("start"))
		else if action is "Switch to development mode" then
			display notification "Starting development servers…" with title "ApplyPilot"
			my finish(my sh("dev"))
		else if action is "Show logs" then
			my sh("logs --open")
		end if
	on error errorText
		display alert "ApplyPilot" message errorText as critical
	end try
end run

on sh(command)
	return do shell script quoted form of cli & " " & command & " 2>&1"
end sh

on finish(output)
	set lastLine to last paragraph of output
	if lastLine is "" and (count of paragraphs of output) > 1 then set lastLine to paragraph -2 of output
	display notification lastLine with title "ApplyPilot"
end finish
