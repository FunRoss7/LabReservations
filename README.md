An rpm that is meant to be installed on a jump box that uses ansible to ssh to lab machines via a group account, changes that password to something random, and sets a time at which that password will be reverted, and changes the login message to indicate who has the machine reserved. also allows the reserver to cancel the reservation or extend it

structure:
reservation playbook
* check if we're using a nonstandard password (indicating we've already reserved the machine)
* if so remove the existing cron job (you'll see it later)
* check if we can't login using the standard password (indicate someone else has it locked, verify that the login prompt idicates this as well)
* put generate a new random password and put it int he vault
* change the password on the target machine to match what's in the vault
* update the login prompt with "user has this machine reserved until datetime"
* setup something like a cron job to reinstitue the original password after a certain time
* keep a record of this reservation from on the local host (not the target machine) for status checking

release reservation playbook
* check if we're not using a nonstandard password (indicating we haven't reserved the machine) and check if we can login using the standard password (indicate someone else has it locked, verify that the login prompt idicates this as well)
* if so exit , nothing to release
* remove the existing password
* set the password back to the original
* update the record on localhost

cli (bash / python prolly)
 * initialize vault and prompts the user for default creds to put in the vault (validate creds before vault entry) (tell user for more detail use these ansible vault commands, vault is here)
 * reserve
 ** ask for a machine name or comma separated list
 ** ask for a time of expiring (accept duration and future timestamp)
 ** reflect the information back to the user and ask for confirmation
   
 * release
 ** ask for a machine name or comma separated list
 ** reflect the information back to the user and ask for confirmation
   
 * view existing reservations
 ** print the record file
   
.spec file that can build on rhel8
 * depend on python 3.6.8
 * ansible 2.16.3
 
