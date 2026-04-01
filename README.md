An rpm that is meant to be installed on a jump box that uses ansible to ssh to lab machines via a group account, changes that password to something random, and sets a time at which that password will be reverted, and changes the login message to indicate who has the machine reserved. also allows the reserver to cancel the reservation or extend it

structure:
reservation playbook
* put generate a new random password and put it int he vault
* change the password on the target machine to match what's in the vault
* update the login prompt with "user has this machine reserved until datetime"

cli (bash / python prolly)
 * initialize vault and prompts the user for default creds to put in the vault (validate creds before vault entry) (tell user for more detail use these ansible vault commands, vault is here)
 * reserve
 * release
 * extend
 * view existing reservations
   
.spec file that can build on rhel8
 * depend on python 3.6.8
 * ansible 2.16.3
 
