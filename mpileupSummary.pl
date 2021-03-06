#!/usr/bin/perl
use warnings;
use strict;

use Getopt::Long qw(:config auto_help pass_through);

my $sampleName = "";
my $proportion = 0;

GetOptions("samplename=s" => \$sampleName,
          "proportion!" => \$proportion) or
  die("Error in command line arguments");

my $assembly = "";

if($sampleName){
  printf("%-15s ", "Sample");
}
if($proportion){
  printf("%-30s %8s %3s %8s %s\n",
         "Assembly", "Position", "Ref", "Coverage",
         " RefP     A     C     G     T     d     i");
} else {
  printf("%-30s %8s %3s %8s %s\n",
         "Assembly", "Position", "Ref", "Coverage",
         "       .   A   C   G   T   d   i");
}

while(<>){
  chomp;
  my @F = split(/\t/);
  if(scalar(@F) <= 4){
    next;
  }
  if($sampleName){
    printf("%-15s ", $sampleName);
  }
  printf("%-30s %8d %3s %8d", $F[0], $F[1], $F[2], $F[3]);
  my $refAllele = $F[2];
  my $coverage = $F[3];
  splice(@F,0,4);
  $_ = $F[0];
  my @inss = m/\+[0-9]+[ACGTNacgtn]+/g;
  my $i = scalar(@inss);
  s/\^.//g;
  s/(\+|-)[0-9]+[ACGTNacgtn]+//g;
  my $r = tr/,.//;
  my $d = tr/*//;
  my $a = tr/aA//;
  my $c = tr/cC//;
  my $g = tr/gG//;
  my $t = tr/tT//;
  if($proportion){
    my $total = $i+$r+$d+$a+$c+$g+$t;
    if($refAllele eq "A"){
      $a = $r;
    } elsif($refAllele eq "C"){
      $c = $r;
    } elsif($refAllele eq "G"){
      $g = $r;
    } elsif($refAllele eq "T"){
      $t = $r;
    }
    ($r, $i, $d, $a, $c, $g, $t) = map {$_ * 100 / $coverage}
      ($r, $i, $d, $a, $c, $g, $t);
    printf(" %5.1f %5.1f %5.1f %5.1f %5.1f %5.1f %5.1f\n",
           $r, $a, $c, $g, $t, $d, $i);
  } else {
    printf(" %8d %3d %3d %3d %3d %3d %3d\n", $r, $a, $c, $g, $t, $d, $i);
  }
}
